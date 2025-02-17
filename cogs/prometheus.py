import psutil
from discord import AutoShardedClient, Interaction, InteractionType
from discord.ext import commands, tasks

from utility.prometheus import Metrics


class PrometheusCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.set_metrics_loop.start()

    async def cog_unload(self) -> None:
        self.set_metrics_loop.cancel()

    @tasks.loop(seconds=5)
    async def set_metrics_loop(self):
        """循環更新延遲、CPU、記憶體使用率"""
        if isinstance(self.bot, AutoShardedClient):
            for shard_id, latency in self.bot.latencies:
                Metrics.LATENCY.labels(shard_id).set(latency)
        else:
            Metrics.LATENCY.labels(None).set(self.bot.latency)

        process = psutil.Process()
        Metrics.CPU_USAGE.set(process.cpu_percent(interval=1))
        Metrics.MEMORY_USAGE.set(process.memory_percent())

    def set_guild_gauges(self):
        """更新伺服器、頻道、使用者總數量"""
        num_of_guilds = len(self.bot.guilds)
        Metrics.GUILDS.set(num_of_guilds)

        num_of_channels = len(set(self.bot.get_all_channels()))
        Metrics.CHANNELS.set(num_of_channels)

        num_of_users = len(set(self.bot.get_all_members()))
        Metrics.USERS.set(num_of_users)

    @commands.Cog.listener()
    async def on_ready(self):
        """當機器人準備好時，設定伺服器數量、連線狀態、可使用指令總數"""
        self.set_guild_gauges()

        Metrics.IS_CONNECTED.labels(None).set(1)

        num_of_commands = len([*self.bot.walk_commands(), *self.bot.tree.walk_commands()])
        Metrics.COMMANDS.set(num_of_commands)

        process = psutil.Process()
        Metrics.PROCESS_START_TIME.set(process.create_time())

    # -------------------------------------------------------------
    # 機器人指令呼叫相關監控
    @commands.Cog.listener()
    async def on_command(self, ctx: commands.Context):
        """當文字指令被呼叫時，設定 Metric"""
        shard_id = ctx.guild.shard_id if ctx.guild else None
        command_name = ctx.command.name if ctx.command else None
        Metrics.COMMAND_EVENTS.labels(shard_id, command_name).inc()

    @commands.Cog.listener()
    async def on_interaction(self, interaction: Interaction):
        """當 Interaction 被呼叫時，設定 Metric"""
        shard_id = interaction.guild.shard_id if interaction.guild else None

        if interaction.type == InteractionType.application_command:
            command_name = interaction.command.name if interaction.command else None
        else:  # 從 View (例如 Button, Dropdown...) 被呼叫
            command_name = None

        Metrics.INTERACTION_EVENTS.labels(shard_id, interaction.type.name, command_name).inc()

    # -------------------------------------------------------------
    # 機器人連線、斷線相關監控
    @commands.Cog.listener()
    async def on_connect(self):
        Metrics.IS_CONNECTED.labels(None).set(1)

    @commands.Cog.listener()
    async def on_resumed(self):
        Metrics.IS_CONNECTED.labels(None).set(1)

    @commands.Cog.listener()
    async def on_disconnect(self):
        Metrics.IS_CONNECTED.labels(None).set(0)

    @commands.Cog.listener()
    async def on_shard_ready(self, shard_id):
        Metrics.IS_CONNECTED.labels(shard_id).set(1)

    @commands.Cog.listener()
    async def on_shard_connect(self, shard_id):
        Metrics.IS_CONNECTED.labels(shard_id).set(1)

    @commands.Cog.listener()
    async def on_shard_resumed(self, shard_id):
        Metrics.IS_CONNECTED.labels(shard_id).set(1)

    @commands.Cog.listener()
    async def on_shard_disconnect(self, shard_id):
        Metrics.IS_CONNECTED.labels(shard_id).set(0)

    # -------------------------------------------------------------
    # 機器人伺服器、成員變動監控
    @commands.Cog.listener()
    async def on_guild_join(self, _):
        self.set_guild_gauges()

    @commands.Cog.listener()
    async def on_guild_remove(self, _):
        self.set_guild_gauges()

    @commands.Cog.listener()
    async def on_guild_channel_create(self, _):
        Metrics.CHANNELS.inc()

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, _):
        Metrics.CHANNELS.dec()

    @commands.Cog.listener()
    async def on_member_join(self, _):
        Metrics.USERS.inc()

    @commands.Cog.listener()
    async def on_member_remove(self, _):
        Metrics.USERS.dec()


async def setup(client: commands.Bot):
    await client.add_cog(PrometheusCog(client))
