import asyncio
from typing import Literal, Optional, Sequence, Union

import discord
import genshin
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import commands

from data.database import SpiralAbyssData, db
from utility import EmbedTemplate, config, custom_log
from yuanshen import draw, genshin_app, parser


class SpiralAbyss:
    """深境螺旋"""

    class AbyssRecordDropdown(discord.ui.Select):
        """選擇深淵歷史紀錄的下拉選單"""

        def __init__(
            self,
            user: Union[discord.User, discord.Member],
            abyss_data_list: Sequence[SpiralAbyssData],
        ):
            def honor(abyss: genshin.models.SpiralAbyss) -> str:
                """判斷一些特殊紀錄，例如12通、單通、雙通"""
                if abyss.total_stars == 36:
                    if abyss.total_battles == 12:
                        return "(👑)"
                    last_battles = abyss.floors[-1].chambers[-1].battles
                    num_of_characters = max(
                        len(last_battles[0].characters), len(last_battles[1].characters)
                    )
                    if num_of_characters == 2:
                        return "(雙通)"
                    if num_of_characters == 1:
                        return "(單通)"
                return ""

            options = [
                discord.SelectOption(
                    label=f"[第 {abyss.season} 期] ★ {abyss.abyss.total_stars} {honor(abyss.abyss)}",
                    description=(
                        f"{abyss.abyss.start_time.astimezone().strftime('%Y.%m.%d')} ~ "
                        f"{abyss.abyss.end_time.astimezone().strftime('%Y.%m.%d')}"
                    ),
                    value=str(i),
                )
                for i, abyss in enumerate(abyss_data_list)
            ]
            super().__init__(placeholder="選擇期數：", options=options)
            self.user = user
            self.abyss_data_list = abyss_data_list

        async def callback(self, interaction: discord.Interaction):
            await interaction.response.defer()
            index = int(self.values[0])
            await SpiralAbyss.presentation(
                interaction, self.user, self.abyss_data_list[index], view_item=self
            )

    class AbyssFloorDropdown(discord.ui.Select):
        """選擇深淵樓層的下拉選單"""

        def __init__(
            self,
            overview: discord.Embed,
            abyss_data: SpiralAbyssData,
            save_or_remove: Literal["SAVE", "REMOVE"],
        ):
            # 第一個選項依據參數顯示為保存或是刪除紀錄
            _description = "保存此次紀錄到資料庫，之後可從歷史紀錄查看" if save_or_remove == "SAVE" else "從資料庫中刪除本次深淵紀錄"
            option = [
                discord.SelectOption(
                    label=f"{'📁 儲存本次紀錄' if save_or_remove == 'SAVE' else '❌ 刪除本次紀錄'}",
                    description=_description,
                    value=save_or_remove,
                )
            ]
            options = option + [
                discord.SelectOption(
                    label=f"[★{floor.stars}] 第 {floor.floor} 層",
                    description=parser.parse_abyss_chamber(floor.chambers[-1]),
                    value=str(i),
                )
                for i, floor in enumerate(abyss_data.abyss.floors)
            ]
            super().__init__(placeholder="選擇樓層：", options=options)
            self.embed = overview
            self.abyss_data = abyss_data
            self.save_or_remove = save_or_remove

        async def callback(self, interaction: discord.Interaction):
            # 儲存或刪除深淵資料
            if self.values[0] == self.save_or_remove:
                # 檢查互動者是否為深淵資料本人
                if interaction.user.id == self.abyss_data.id:
                    if self.save_or_remove == "SAVE":
                        await db.spiral_abyss.add(self.abyss_data)
                        await interaction.response.send_message(
                            embed=EmbedTemplate.normal("已儲存本次深淵紀錄"), ephemeral=True
                        )
                    else:  # self.save_or_remove == 'REMOVE'
                        await db.spiral_abyss.remove(self.abyss_data.id, self.abyss_data.season)
                        await interaction.response.send_message(
                            embed=EmbedTemplate.normal("已刪除本次深淵紀錄"), ephemeral=True
                        )
                else:
                    await interaction.response.send_message(
                        embed=EmbedTemplate.error("僅限本人才能操作"), ephemeral=True
                    )
            else:  # 繪製樓層圖片
                fp = draw.draw_abyss_card(
                    self.abyss_data.abyss.floors[int(self.values[0])],
                    self.abyss_data.characters,
                )
                fp.seek(0)
                self.embed.set_image(url="attachment://image.jpeg")
                await interaction.response.edit_message(
                    embed=self.embed, attachments=[discord.File(fp, "image.jpeg")]
                )

    @staticmethod
    async def presentation(
        interaction: discord.Interaction,
        user: Union[discord.User, discord.Member],
        abyss_data: SpiralAbyssData,
        *,
        view_item: Optional[discord.ui.Item] = None,
    ):
        embed = parser.parse_abyss_overview(abyss_data.abyss)
        embed.title = f"{user.display_name} 的深境螺旋戰績"
        embed.set_thumbnail(url=user.display_avatar.url)
        view = None
        if len(abyss_data.abyss.floors) > 0:
            view = discord.ui.View(timeout=config.discord_view_short_timeout)
            if view_item:  # 從歷史紀錄取得資料，所以第一個選項是刪除紀錄
                view.add_item(SpiralAbyss.AbyssFloorDropdown(embed, abyss_data, "REMOVE"))
                view.add_item(view_item)
            else:  # 從Hoyolab取得資料，所以第一個選項是保存紀錄
                view.add_item(SpiralAbyss.AbyssFloorDropdown(embed, abyss_data, "SAVE"))
        await interaction.edit_original_response(embed=embed, view=view, attachments=[])

    @staticmethod
    async def abyss(
        interaction: discord.Interaction,
        user: Union[discord.User, discord.Member],
        season_choice: Literal["THIS_SEASON", "PREVIOUS_SEASON", "HISTORICAL_RECORD"],
    ):
        if season_choice == "HISTORICAL_RECORD":  # 查詢歷史紀錄
            abyss_data_list = await db.spiral_abyss.get(user.id)
            if len(abyss_data_list) == 0:
                await interaction.response.send_message(
                    embed=EmbedTemplate.normal("此使用者沒有保存任何歷史紀錄")
                )
            else:
                view = discord.ui.View(timeout=config.discord_view_short_timeout)
                view.add_item(SpiralAbyss.AbyssRecordDropdown(user, abyss_data_list))
                await interaction.response.send_message(view=view)
        else:  # 查詢 Hoyolab 紀錄 (THIS_SEASON、PREVIOUS_SEASON)
            try:
                defer, abyss_data = await asyncio.gather(
                    interaction.response.defer(),
                    genshin_app.get_spiral_abyss(user.id, (season_choice == "PREVIOUS_SEASON")),
                )
            except Exception as e:
                await interaction.edit_original_response(embed=EmbedTemplate.error(e))
            else:
                await SpiralAbyss.presentation(interaction, user, abyss_data)


class SpiralAbyssCog(commands.Cog, name="深境螺旋"):
    """斜線指令"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -------------------------------------------------------------
    # 取得深境螺旋資訊
    @app_commands.command(name="abyss深淵紀錄", description="查詢深境螺旋紀錄")
    @app_commands.checks.cooldown(1, config.slash_cmd_cooldown)
    @app_commands.rename(season="時間", user="使用者")
    @app_commands.describe(season="選擇本期、上期或是歷史紀錄", user="查詢其他成員的資料，不填寫則查詢自己")
    @app_commands.choices(
        season=[
            Choice(name="本期紀錄", value="THIS_SEASON"),
            Choice(name="上期紀錄", value="PREVIOUS_SEASON"),
            Choice(name="歷史紀錄", value="HISTORICAL_RECORD"),
        ]
    )
    @custom_log.SlashCommandLogger
    async def slash_abyss(
        self,
        interaction: discord.Interaction,
        season: Literal["THIS_SEASON", "PREVIOUS_SEASON", "HISTORICAL_RECORD"],
        user: Optional[discord.User] = None,
    ):
        await SpiralAbyss.abyss(interaction, user or interaction.user, season)

    @slash_abyss.error
    async def on_slash_abyss_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(
                embed=EmbedTemplate.error(f"使用指令的間隔為{config.slash_cmd_cooldown}秒，請稍後再使用~"),
                ephemeral=True,
            )


async def setup(client: commands.Bot):
    await client.add_cog(SpiralAbyssCog(client))

    # -------------------------------------------------------------
    # 下面為Context Menu指令
    @client.tree.context_menu(name="深淵紀錄(上期)")
    @custom_log.ContextCommandLogger
    async def context_abyss_previous(interaction: discord.Interaction, user: discord.User):
        await SpiralAbyss.abyss(interaction, user, "PREVIOUS_SEASON")

    @client.tree.context_menu(name="深淵紀錄(本期)")
    @custom_log.ContextCommandLogger
    async def context_abyss(interaction: discord.Interaction, user: discord.User):
        await SpiralAbyss.abyss(interaction, user, "THIS_SEASON")
