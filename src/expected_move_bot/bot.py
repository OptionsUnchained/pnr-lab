from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from io import BytesIO

import discord
from discord import app_commands
from discord.ext import commands, tasks

from expected_move_bot.calculations import format_table, iv_label
from expected_move_bot.config import Settings
from expected_move_bot.earnings import (
    EARNINGS_PROVIDER_SYMBOLS,
    format_earnings,
    format_earnings_lee,
)
from expected_move_bot.epr import TastytradeEprData, format_percent
from expected_move_bot.epr_watchlist import (
    EPR_WATCHLIST_SYMBOLS,
    EprHistoryStore,
    EprWatchlistReport,
    build_epr_watchlist_report,
    format_epr_watchlist,
    should_capture_epr_watchlist,
)
from expected_move_bot.gex import GexExpirySnapshot, GexStrikeSnapshot
from expected_move_bot.gex_data import TastytradeGexData
from expected_move_bot.gex_history import (
    GexCaptureReport,
    GexCaptureStatus,
    GexHistoryStore,
    format_gex_collection_section,
    format_gex_history_table,
    should_capture_gex_history,
)
from expected_move_bot.gex_image import render_gex_expiry, render_gex_strikes
from expected_move_bot.market_data import TastytradeMarketData
from expected_move_bot.movers import (
    PACIFIC,
    MarketMoversSnapshot,
    MoversMode,
    mode_label,
    scheduled_report,
)
from expected_move_bot.movers_image import render_market_movers
from expected_move_bot.options_flow import OptionsFlowSnapshot
from expected_move_bot.options_flow_data import TastytradeOptionsFlowData
from expected_move_bot.options_flow_image import render_options_flow

LOGGER = logging.getLogger(__name__)


class ExpectedMoveBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        super().__init__(command_prefix=commands.when_mentioned, intents=discord.Intents.none())
        self.settings = settings
        self.market_data = TastytradeMarketData(settings.tt_secret, settings.tt_refresh)
        self.gex_data = TastytradeGexData(settings.tt_secret, settings.tt_refresh)
        self.epr_data = TastytradeEprData(
            settings.tt_secret,
            settings.tt_refresh,
            settings.tt_account_number,
        )
        self.options_flow_data = TastytradeOptionsFlowData(
            settings.tt_secret, settings.tt_refresh
        )
        self.gex_history_store = (
            GexHistoryStore(settings.database_url) if settings.database_url else None
        )
        self.epr_history_store = (
            EprHistoryStore(settings.database_url) if settings.database_url else None
        )
        self._last_movers_slot: tuple[str, int, int] | None = None
        self._last_gex_history_date: date | None = None
        self._last_epr_watchlist_date: date | None = None
        self._gex_history_lock = asyncio.Lock()
        self._epr_watchlist_lock = asyncio.Lock()

    async def setup_hook(self) -> None:
        if self.settings.discord_guild_id:
            guild = discord.Object(id=self.settings.discord_guild_id)
            self.tree.copy_global_to(guild=guild)
            commands_synced = await self.tree.sync(guild=guild)
            LOGGER.info("Synced %d command(s) to guild %d", len(commands_synced), guild.id)
        else:
            commands_synced = await self.tree.sync()
            LOGGER.info("Synced %d global command(s)", len(commands_synced))

        if self.settings.movers_channel_id is not None:
            self.movers_scheduler.start()
            LOGGER.info(
                "Market-movers scheduler enabled for channel %d",
                self.settings.movers_channel_id,
            )

        if self.gex_history_store is not None:
            try:
                await self.gex_history_store.open()
            except Exception:
                LOGGER.exception("Could not initialize the GEX history database")
                self.gex_history_store = None
            else:
                self.gex_history_scheduler.start()
                LOGGER.info(
                    "GEX history enabled for %d symbols and %d expirations",
                    len(self.settings.gex_history_symbols),
                    len(self.settings.gex_history_expirations),
                )

        if self.epr_history_store is not None:
            try:
                await self.epr_history_store.open()
            except Exception:
                LOGGER.exception("Could not initialize the EPR history database")
                self.epr_history_store = None

        if self.settings.epr_channel_id is not None:
            self.epr_watchlist_scheduler.start()
            LOGGER.info(
                "EPR watchlist scheduler enabled for channel %d",
                self.settings.epr_channel_id,
            )

    async def close(self) -> None:
        if self.movers_scheduler.is_running():
            self.movers_scheduler.cancel()
        if self.gex_history_scheduler.is_running():
            self.gex_history_scheduler.cancel()
        if self.epr_watchlist_scheduler.is_running():
            self.epr_watchlist_scheduler.cancel()
        if self.gex_history_store is not None:
            await self.gex_history_store.close()
        if self.epr_history_store is not None:
            await self.epr_history_store.close()
        await super().close()

    @tasks.loop(seconds=20)
    async def movers_scheduler(self) -> None:
        now = datetime.now(PACIFIC)
        report = scheduled_report(now)
        if report is None:
            return
        slot = (now.date().isoformat(), now.hour, now.minute)
        if slot == self._last_movers_slot:
            return
        self._last_movers_slot = slot

        try:
            snapshot = await self.market_data.market_movers_snapshot(mode=report.mode)
            channel_id = self.settings.movers_channel_id
            if channel_id is None:
                return
            channel = self.get_channel(channel_id) or await self.fetch_channel(channel_id)
            if not isinstance(channel, discord.abc.Messageable):
                raise TypeError(f"Discord channel {channel_id} cannot receive messages")
            await channel.send(file=create_movers_file(snapshot, report.label))
            LOGGER.info("Posted scheduled %s market-movers report", report.label)
        except Exception:
            LOGGER.exception("Scheduled market-movers report failed")

    @movers_scheduler.before_loop
    async def before_movers_scheduler(self) -> None:
        await self.wait_until_ready()

    @tasks.loop(seconds=30)
    async def gex_history_scheduler(self) -> None:
        now = datetime.now(PACIFIC)
        if not should_capture_gex_history(now, self._last_gex_history_date):
            return
        self._last_gex_history_date = now.date()
        try:
            report = await self.capture_gex_history()
        except Exception:
            LOGGER.exception("Scheduled GEX history capture failed")
            self._last_gex_history_date = None
            return

        LOGGER.info(
            "Saved %d/%d scheduled GEX history snapshots",
            report.saved_count,
            report.expected_count,
        )
        try:
            await self.post_gex_collection_report(report)
        except Exception:
            LOGGER.exception("Could not post the daily GEX collection report")

    @gex_history_scheduler.before_loop
    async def before_gex_history_scheduler(self) -> None:
        await self.wait_until_ready()

    @tasks.loop(seconds=30)
    async def epr_watchlist_scheduler(self) -> None:
        now = datetime.now(PACIFIC)
        if not should_capture_epr_watchlist(now, self._last_epr_watchlist_date):
            return
        self._last_epr_watchlist_date = now.date()
        try:
            report = await self.capture_epr_watchlist()
            await self.post_epr_watchlist_report(report)
        except Exception:
            LOGGER.exception("Scheduled EPR watchlist collection failed")
            self._last_epr_watchlist_date = None
            return
        LOGGER.info(
            "Posted scheduled EPR watchlist with %d/%d symbols",
            report.successful_count,
            len(report.rows),
        )

    @epr_watchlist_scheduler.before_loop
    async def before_epr_watchlist_scheduler(self) -> None:
        await self.wait_until_ready()

    async def capture_epr_watchlist(self) -> EprWatchlistReport:
        async with self._epr_watchlist_lock:
            captured_at = datetime.now(PACIFIC)
            display_symbols = EPR_WATCHLIST_SYMBOLS
            provider_symbols = tuple(
                EARNINGS_PROVIDER_SYMBOLS.get(symbol, symbol)
                for symbol in display_symbols
            )
            previous = {}
            if self.epr_history_store is not None:
                try:
                    previous = await self.epr_history_store.fetch_previous(
                        display_symbols,
                        captured_at.date(),
                    )
                except Exception:
                    LOGGER.exception("Could not load the prior EPR watchlist collection")

            results = await self.epr_data.snapshots(provider_symbols)
            report = build_epr_watchlist_report(
                display_symbols,
                results,
                previous,
                captured_at,
            )
            if self.epr_history_store is not None:
                try:
                    await self.epr_history_store.save_report(report)
                except Exception:
                    LOGGER.exception("Could not save the EPR watchlist collection")
            return report

    async def post_epr_watchlist_report(self, report: EprWatchlistReport) -> None:
        channel_id = self.settings.epr_channel_id
        if channel_id is None:
            return
        channel = self.get_channel(channel_id) or await self.fetch_channel(channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            raise TypeError(f"Discord channel {channel_id} cannot receive messages")
        await channel.send(embed=create_epr_watchlist_embed(report))

    async def capture_gex_history(self) -> GexCaptureReport:
        store = self.gex_history_store
        if store is None:
            raise RuntimeError("GEX history database is not configured")
        async with self._gex_history_lock:
            semaphore = asyncio.Semaphore(2)

            async def capture_symbol(symbol: str) -> list[GexCaptureStatus]:
                async with semaphore:
                    try:
                        snapshots = await self.gex_data.history_snapshots(
                            symbol,
                            self.settings.gex_history_expirations,
                        )
                    except Exception as exc:
                        LOGGER.exception("GEX history pull failed for %s", symbol)
                        return [
                            GexCaptureStatus(
                                symbol=symbol,
                                expiration_date=expiration,
                                saved=False,
                                error=type(exc).__name__,
                            )
                            for expiration in self.settings.gex_history_expirations
                        ]

                    by_expiration = {
                        snapshot.expiration_date: snapshot for snapshot in snapshots
                    }
                    statuses: list[GexCaptureStatus] = []
                    for expiration in self.settings.gex_history_expirations:
                        snapshot = by_expiration.get(expiration)
                        if snapshot is None:
                            statuses.append(
                                GexCaptureStatus(
                                    symbol=symbol,
                                    expiration_date=expiration,
                                    saved=False,
                                    error="No data returned",
                                )
                            )
                            continue
                        try:
                            await store.save_snapshot(snapshot)
                        except Exception as exc:
                            LOGGER.exception(
                                "Could not save GEX history for %s %s",
                                symbol,
                                expiration,
                            )
                            statuses.append(
                                GexCaptureStatus(
                                    symbol=symbol,
                                    expiration_date=expiration,
                                    saved=False,
                                    error=type(exc).__name__,
                                )
                            )
                            continue
                        statuses.append(
                            GexCaptureStatus(
                                symbol=symbol,
                                expiration_date=expiration,
                                saved=True,
                                bias=snapshot.gex_bias,
                                contracts_received=snapshot.contracts_received,
                                contracts_requested=snapshot.contracts_requested,
                            )
                        )
                    return statuses

            results = await asyncio.gather(
                *(capture_symbol(symbol) for symbol in self.settings.gex_history_symbols),
                return_exceptions=True,
            )
            statuses: list[GexCaptureStatus] = []
            for symbol, result in zip(
                self.settings.gex_history_symbols,
                results,
                strict=True,
            ):
                if isinstance(result, BaseException):
                    LOGGER.error(
                        "GEX history capture failed for %s",
                        symbol,
                        exc_info=(type(result), result, result.__traceback__),
                    )
                    statuses.extend(
                        GexCaptureStatus(
                            symbol=symbol,
                            expiration_date=expiration,
                            saved=False,
                            error=type(result).__name__,
                        )
                        for expiration in self.settings.gex_history_expirations
                    )
                else:
                    statuses.extend(result)
            return GexCaptureReport(
                captured_at=datetime.now(PACIFIC),
                statuses=tuple(statuses),
            )

    async def post_gex_collection_report(self, report: GexCaptureReport) -> None:
        channel_id = self.settings.gex_history_channel_id
        if channel_id is None:
            return
        channel = self.get_channel(channel_id) or await self.fetch_channel(channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            raise TypeError(f"Discord channel {channel_id} cannot receive messages")

        if report.complete_count == report.expected_count:
            color = 0x57F287
        elif report.saved_count:
            color = 0xFEE75C
        else:
            color = 0xED4245
        embed = discord.Embed(
            title="📊 Daily GEX Collection",
            description=(
                f"**{report.captured_at:%b %d, %Y} · 6:45 AM PT**\n"
                "Bias is net GEX as a percentage of gross GEX."
            ),
            color=color,
            timestamp=report.captured_at,
        )
        for expiration in self.settings.gex_history_expirations:
            dte = (expiration - report.captured_at.date()).days
            embed.add_field(
                name=f"{expiration:%b %d, %Y} · {dte} DTE",
                value=format_gex_collection_section(report, expiration),
                inline=False,
            )
        embed.set_footer(
            text=(
                f"Stored {report.saved_count}/{report.expected_count} · "
                f"Complete {report.complete_count}/{report.expected_count} · "
                "✅ complete  ⚠️ partial  ❌ failed"
            )
        )
        await channel.send(embed=embed)


def create_movers_file(
    snapshot: MarketMoversSnapshot, report_label: str = "On Demand"
) -> discord.File:
    image_bytes = render_market_movers(snapshot, report_label)
    return discord.File(
        BytesIO(image_bytes),
        filename="market-movers.png",
        description="Top 15 gainers and losers among companies with market caps of at least $20B",
    )


def create_gex_file(snapshot: GexExpirySnapshot | GexStrikeSnapshot) -> discord.File:
    if isinstance(snapshot, GexStrikeSnapshot):
        image_bytes = render_gex_strikes(snapshot)
        filename = f"gex-{snapshot.symbol.lower()}-{snapshot.expiration_date}.png"
        description = (
            f"Gamma exposure by strike for {snapshot.symbol}, "
            f"{snapshot.expiration_date:%B %d, %Y}"
        )
    else:
        image_bytes = render_gex_expiry(snapshot)
        filename = f"gex-{snapshot.symbol.lower()}-by-expiry.png"
        description = f"Gamma exposure by expiration for {snapshot.symbol}"
    return discord.File(BytesIO(image_bytes), filename=filename, description=description)


def create_options_flow_file(snapshot: OptionsFlowSnapshot) -> discord.File:
    image_bytes = render_options_flow(snapshot)
    filename = (
        f"options-flow-{snapshot.symbol.lower()}-{snapshot.expiration_date}.png"
    )
    description = (
        f"Top 10 option strikes by session volume for {snapshot.symbol}, "
        f"{snapshot.expiration_date:%B %d, %Y}"
    )
    return discord.File(BytesIO(image_bytes), filename=filename, description=description)


def create_epr_watchlist_embed(report: EprWatchlistReport) -> discord.Embed:
    if report.failure_count == 0:
        color = 0x57F287
    elif report.successful_count:
        color = 0xFEE75C
    else:
        color = 0xED4245
    embed = discord.Embed(
        title="🛡️ EPR Watchlist",
        description=format_epr_watchlist(report),
        color=color,
        timestamp=report.captured_at,
    )
    embed.set_footer(
        text=(
            f"Retrieved {report.successful_count}/{len(report.rows)} • "
            "Changes are percentage points in EPR magnitude • "
            "Positive = wider, negative = narrower • Read-only dry runs; no orders"
        )
    )
    return embed


def create_bot(settings: Settings) -> ExpectedMoveBot:
    bot = ExpectedMoveBot(settings)

    @bot.tree.command(
        name="expected-move",
        description="Show expected moves using Tastytrade's platform calculation.",
    )
    @app_commands.describe(ticker="Stock or ETF ticker, for example CRWD or SPY")
    @app_commands.checks.cooldown(1, settings.command_cooldown_seconds, key=lambda i: i.user.id)
    async def expected_move(interaction: discord.Interaction, ticker: str) -> None:
        await interaction.response.defer(thinking=True)
        try:
            snapshot = await bot.market_data.expected_move_snapshot(ticker)
            label, emoji, color = iv_label(snapshot.iv)
            rank_text = (
                f" • **IV Rank:** {snapshot.iv_rank:.1%}" if snapshot.iv_rank is not None else ""
            )
            embed = discord.Embed(
                title=f"📐 Expected Move — ${snapshot.symbol}",
                description=(
                    f"**Current Price:** ${snapshot.price:,.2f}  •  "
                    f"**IVx:** {snapshot.iv:.1%} {emoji} {label}{rank_text}\n\n"
                    "📅 **Expected Move by Expiration**\n"
                    f"{format_table(snapshot.rows, snapshot.price)}"
                ),
                color=color,
            )
            embed.set_footer(
                text=(
                    "EM = 60% ATM straddle + 30% first OTM strangle + 10% second OTM "
                    "strangle • Live Tastytrade marks • "
                    "For information only; verify before trading."
                )
            )
            await interaction.followup.send(embed=embed)
        except (ValueError, LookupError) as exc:
            await interaction.followup.send(f"⚠️ {exc}", ephemeral=True)
        except Exception:
            LOGGER.exception("Expected-move command failed for %r", ticker)
            await interaction.followup.send(
                "⚠️ I couldn't retrieve market data right now. Check the bot logs and try again.",
                ephemeral=True,
            )

    @expected_move.error
    async def expected_move_error(
        interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.CommandOnCooldown):
            message = f"Please wait {error.retry_after:.1f} seconds and try again."
        else:
            LOGGER.exception("Discord application-command error", exc_info=error)
            message = "The command failed unexpectedly. Check the bot logs."

        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    @bot.tree.command(
        name="epr",
        description="Show Tastytrade's pre-trade expected price range for a stock or ETF.",
    )
    @app_commands.describe(ticker="Stock or ETF ticker, for example QQQ or SMH")
    @app_commands.checks.cooldown(1, settings.command_cooldown_seconds, key=lambda i: i.user.id)
    async def epr(interaction: discord.Interaction, ticker: str) -> None:
        await interaction.response.defer(thinking=True)
        try:
            snapshot = await bot.epr_data.snapshot(ticker)
            embed = discord.Embed(
                title=f"🛡️ Expected Price Range — ${snapshot.symbol}",
                description=(
                    f"**EPR Down:** {format_percent(snapshot.down_percent, '-')}\n"
                    f"**EPR Up:** {format_percent(snapshot.up_percent, '+')}"
                ),
                color=discord.Color.blurple(),
            )
            if (
                snapshot.stress_down_percent is not None
                and snapshot.stress_up_percent is not None
            ):
                embed.add_field(
                    name="Applied Stress Range",
                    value=(
                        f"{format_percent(snapshot.stress_down_percent, '-')} to "
                        f"{format_percent(snapshot.stress_up_percent, '+')}"
                    ),
                    inline=False,
                )
            embed.add_field(name="Source", value=snapshot.source, inline=False)
            embed.set_footer(
                text=(
                    "Read-only margin dry run; no order is placed. "
                    "EPR is account-scoped and can change with volatility."
                )
            )
            await interaction.followup.send(embed=embed)
        except (ValueError, LookupError) as exc:
            await interaction.followup.send(f"⚠️ {exc}", ephemeral=True)
        except Exception:
            LOGGER.exception("EPR command failed for %r", ticker)
            await interaction.followup.send(
                "⚠️ I couldn't retrieve EPR right now. Check the bot logs and try again.",
                ephemeral=True,
            )

    @epr.error
    async def epr_error(
        interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.CommandOnCooldown):
            message = f"Please wait {error.retry_after:.1f} seconds and try again."
        else:
            LOGGER.exception("Discord EPR command error", exc_info=error)
            message = "The command failed unexpectedly. Check the bot logs."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    @bot.tree.command(
        name="epr-wl",
        description="Show EPR and prior-day changes for the complete EPR watchlist.",
    )
    @app_commands.checks.cooldown(1, 300.0, key=lambda i: i.user.id)
    async def epr_watchlist(interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        try:
            report = await bot.capture_epr_watchlist()
            await interaction.followup.send(embed=create_epr_watchlist_embed(report))
        except Exception:
            LOGGER.exception("EPR-watchlist command failed")
            await interaction.followup.send(
                "⚠️ I couldn't retrieve the EPR watchlist right now. "
                "Check the bot logs and try again.",
                ephemeral=True,
            )

    @epr_watchlist.error
    async def epr_watchlist_error(
        interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.CommandOnCooldown):
            message = f"Please wait {error.retry_after:.1f} seconds and try again."
        else:
            LOGGER.exception("Discord EPR-watchlist command error", exc_info=error)
            message = "The command failed unexpectedly. Check the bot logs."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    @bot.tree.command(
        name="market-movers",
        description="Show the top 15 gainers and losers among $20B+ companies.",
    )
    @app_commands.describe(report="Choose the market session and comparison baseline")
    @app_commands.choices(
        report=[
            app_commands.Choice(name="Premarket vs prior close", value="premarket"),
            app_commands.Choice(name="Regular session vs prior close", value="regular"),
            app_commands.Choice(name="After market vs today's close", value="after-market"),
        ]
    )
    @app_commands.checks.cooldown(1, 30.0, key=lambda i: i.user.id)
    async def market_movers(
        interaction: discord.Interaction,
        report: app_commands.Choice[str] | None = None,
    ) -> None:
        await interaction.response.defer(thinking=True)
        try:
            mode = MoversMode(report.value) if report is not None else MoversMode.REGULAR
            snapshot = await bot.market_data.market_movers_snapshot(mode=mode)
            await interaction.followup.send(
                file=create_movers_file(snapshot, mode_label(mode))
            )
        except (ValueError, LookupError) as exc:
            await interaction.followup.send(f"⚠️ {exc}", ephemeral=True)
        except Exception:
            LOGGER.exception("Market-movers command failed")
            await interaction.followup.send(
                "⚠️ I couldn't retrieve market-movers data right now. "
                "Check the bot logs and try again.",
                ephemeral=True,
            )

    @market_movers.error
    async def market_movers_error(
        interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.CommandOnCooldown):
            message = f"Please wait {error.retry_after:.1f} seconds and try again."
        else:
            LOGGER.exception("Discord market-movers command error", exc_info=error)
            message = "The command failed unexpectedly. Check the bot logs."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    @bot.tree.command(
        name="earnings",
        description="Show upcoming earnings dates for the tracked stocks.",
    )
    @app_commands.checks.cooldown(1, 30.0, key=lambda i: i.user.id)
    async def earnings(interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        try:
            snapshot = await bot.market_data.earnings_snapshot()
            embed = discord.Embed(
                title="📅 Upcoming Earnings",
                description=format_earnings(snapshot),
                color=0x5865F2,
            )
            embed.set_footer(
                text=(
                    "✅ Tasty-confirmed • No mark: Tasty estimate • "
                    "~ Historical estimate • ❗ <22 days • ‼️ <12 days"
                )
            )
            await interaction.followup.send(embed=embed)
        except Exception:
            LOGGER.exception("Earnings command failed")
            await interaction.followup.send(
                "⚠️ I couldn't retrieve earnings dates right now. "
                "Check the bot logs and try again.",
                ephemeral=True,
            )

    @earnings.error
    async def earnings_error(
        interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.CommandOnCooldown):
            message = f"Please wait {error.retry_after:.1f} seconds and try again."
        else:
            LOGGER.exception("Discord earnings command error", exc_info=error)
            message = "The command failed unexpectedly. Check the bot logs."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    @bot.tree.command(
        name="earnings-lee",
        description="Show upcoming earnings in Lee's original text layout.",
    )
    @app_commands.checks.cooldown(1, 30.0, key=lambda i: i.user.id)
    async def earnings_lee(interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        try:
            snapshot = await bot.market_data.earnings_snapshot()
            embed = discord.Embed(
                title="📅 Upcoming Earnings",
                description=format_earnings_lee(snapshot),
                color=0x5865F2,
            )
            embed.set_footer(
                text=(
                    "✅ Tasty-confirmed • No mark: Tasty estimate • "
                    "~ Historical estimate • ❗ <22 days • ‼️ <12 days"
                )
            )
            await interaction.followup.send(embed=embed)
        except Exception:
            LOGGER.exception("Earnings-Lee command failed")
            await interaction.followup.send(
                "⚠️ I couldn't retrieve earnings dates right now. "
                "Check the bot logs and try again.",
                ephemeral=True,
            )

    @earnings_lee.error
    async def earnings_lee_error(
        interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.CommandOnCooldown):
            message = f"Please wait {error.retry_after:.1f} seconds and try again."
        else:
            LOGGER.exception("Discord earnings-lee command error", exc_info=error)
            message = "The command failed unexpectedly. Check the bot logs."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    @bot.tree.command(
        name="gex",
        description="Chart estimated dealer gamma exposure by expiry or monthly strike.",
    )
    @app_commands.describe(
        ticker="Stock or ETF ticker, for example IWM or OKTA",
        expiration="Optional monthly expiration; leave blank for GEX by expiry",
    )
    @app_commands.checks.cooldown(1, 45.0, key=lambda i: i.user.id)
    async def gex(
        interaction: discord.Interaction,
        ticker: str,
        expiration: str | None = None,
    ) -> None:
        await interaction.response.defer(thinking=True)
        try:
            if expiration:
                snapshot = await bot.gex_data.strike_snapshot(ticker, expiration)
            else:
                snapshot = await bot.gex_data.expiry_snapshot(ticker)
            if (
                isinstance(snapshot, GexStrikeSnapshot)
                and bot.gex_history_store is not None
                and snapshot.symbol in settings.gex_history_symbols
                and snapshot.expiration_date in settings.gex_history_expirations
            ):
                try:
                    await bot.gex_history_store.save_snapshot_if_absent(snapshot)
                except Exception:
                    LOGGER.exception(
                        "Could not save manual GEX history snapshot for %s %s",
                        snapshot.symbol,
                        snapshot.expiration_date,
                    )
            await interaction.followup.send(file=create_gex_file(snapshot))
        except (ValueError, LookupError) as exc:
            await interaction.followup.send(f"⚠️ {exc}", ephemeral=True)
        except Exception:
            LOGGER.exception("GEX command failed for %r %r", ticker, expiration)
            await interaction.followup.send(
                "⚠️ I couldn't retrieve enough GEX data right now. "
                "Check the bot logs and try again.",
                ephemeral=True,
            )

    @bot.tree.command(
        name="options-flow",
        description="Show the top 10 strikes by today's volume for a monthly expiration.",
    )
    @app_commands.describe(
        ticker="Stock or ETF ticker, for example NVDA or SPY",
        expiration="Monthly expiration",
    )
    @app_commands.checks.cooldown(1, 45.0, key=lambda i: i.user.id)
    async def options_flow(
        interaction: discord.Interaction,
        ticker: str,
        expiration: str,
    ) -> None:
        await interaction.response.defer(thinking=True)
        try:
            snapshot = await bot.options_flow_data.snapshot(ticker, expiration)
            await interaction.followup.send(file=create_options_flow_file(snapshot))
        except (ValueError, LookupError) as exc:
            await interaction.followup.send(f"⚠️ {exc}", ephemeral=True)
        except Exception:
            LOGGER.exception("Options-flow command failed for %r %r", ticker, expiration)
            await interaction.followup.send(
                "⚠️ I couldn't retrieve enough options-flow data right now. "
                "Check the bot logs and try again.",
                ephemeral=True,
            )

    @bot.tree.command(
        name="gex-history",
        description="Show daily GEX bias and wall history for a tracked monthly expiration.",
    )
    @app_commands.describe(
        ticker="Tracked stock",
        expiration="Tracked monthly expiration",
        days="Calendar-day lookback",
    )
    @app_commands.choices(
        ticker=[
            app_commands.Choice(name=symbol, value=symbol)
            for symbol in ("NVDA", "AVGO", "META", "AMZN", "GOOGL", "AAPL", "TSLA", "AMD")
        ],
        expiration=[
            app_commands.Choice(name="Nov 20, 2026", value="2026-11-20"),
            app_commands.Choice(name="Dec 18, 2026", value="2026-12-18"),
        ],
        days=[
            app_commands.Choice(name="7 days", value=7),
            app_commands.Choice(name="14 days", value=14),
            app_commands.Choice(name="30 days", value=30),
            app_commands.Choice(name="60 days", value=60),
            app_commands.Choice(name="90 days", value=90),
        ],
    )
    @app_commands.checks.cooldown(1, 10.0, key=lambda i: i.user.id)
    async def gex_history(
        interaction: discord.Interaction,
        ticker: app_commands.Choice[str],
        expiration: app_commands.Choice[str],
        days: app_commands.Choice[int] | None = None,
    ) -> None:
        await interaction.response.defer(thinking=True)
        store = bot.gex_history_store
        if store is None:
            await interaction.followup.send(
                "⚠️ GEX history is not enabled. Add a Railway PostgreSQL database "
                "and expose its DATABASE_URL to the bot service.",
                ephemeral=True,
            )
            return
        expiration_date = date.fromisoformat(expiration.value)
        lookback = days.value if days is not None else 30
        try:
            points = await store.fetch_history(ticker.value, expiration_date, lookback)
            if not points:
                await interaction.followup.send(
                    "No saved observations exist for that ticker and expiration yet. "
                    "The daily collector runs at 6:45 AM PT on trading weekdays; "
                    "running the matching `/gex` command also saves today's snapshot.",
                    ephemeral=True,
                )
                return
            latest = points[-1]
            color = 0x63E6A0 if latest.bias >= 0 else 0xFF454B
            embed = discord.Embed(
                title=(
                    f"GEX History — {ticker.value} · "
                    f"{expiration_date:%b} {expiration_date.day}"
                ),
                description=format_gex_history_table(points),
                color=color,
            )
            embed.set_footer(
                text=(
                    "Bias = net GEX ÷ gross GEX • PutW/CallW = largest walls • "
                    "Call2 = second-largest call wall • One observation per trading day"
                )
            )
            await interaction.followup.send(embed=embed)
        except Exception:
            LOGGER.exception(
                "GEX-history command failed for %s %s",
                ticker.value,
                expiration.value,
            )
            await interaction.followup.send(
                "⚠️ I couldn't read GEX history right now. Check the bot logs and try again.",
                ephemeral=True,
            )

    @gex.autocomplete("expiration")
    @options_flow.autocomplete("expiration")
    async def gex_expiration_autocomplete(
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        ticker = str(getattr(interaction.namespace, "ticker", "")).strip()
        if not ticker:
            return []
        try:
            expirations = await bot.gex_data.regular_expirations(ticker)
        except Exception:
            return []
        current_lower = current.lower().strip()
        choices = []
        today = datetime.now(PACIFIC).date()
        for expiration_date in expirations:
            name = (
                f"{expiration_date:%b} {expiration_date.day}, {expiration_date.year} "
                f"({(expiration_date - today).days} DTE)"
            )
            if current_lower and current_lower not in name.lower():
                continue
            choices.append(
                app_commands.Choice(name=name, value=expiration_date.isoformat())
            )
            if len(choices) == 25:
                break
        return choices

    @gex.error
    async def gex_error(
        interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.CommandOnCooldown):
            message = f"Please wait {error.retry_after:.1f} seconds and try again."
        else:
            LOGGER.exception("Discord GEX command error", exc_info=error)
            message = "The command failed unexpectedly. Check the bot logs."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    @options_flow.error
    async def options_flow_error(
        interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.CommandOnCooldown):
            message = f"Please wait {error.retry_after:.1f} seconds and try again."
        else:
            LOGGER.exception("Discord options-flow command error", exc_info=error)
            message = "The command failed unexpectedly. Check the bot logs."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    return bot


def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = Settings.from_environment()
    create_bot(settings).run(settings.discord_token, log_handler=None)
