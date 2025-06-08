
import discord
from discord.ext import commands
from discord import app_commands, ui
import sqlite3
import random
import os
import asyncio
from aiohttp import web

# --- DBセットアップ ---
conn = sqlite3.connect("achievement_settings.db")
c = conn.cursor()
c.execute("""
CREATE TABLE IF NOT EXISTS achievement_channels (
    guild_id INTEGER PRIMARY KEY,
    channel_id INTEGER
)
""")
conn.commit()

# --- Bot初期化 ---
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- カテゴリー管理メモリ ---
categories = {}  # {guild_id: {category_id: {"name":..., "emoji":...}}}

# --- UIクラス（チケットビュー） ---
class TicketView(ui.View):
    def __init__(self, categories_data):
        super().__init__(timeout=None)
        options = []
        for cat in categories_data:
            label = cat["name"]
            emoji = cat["emoji"]
            options.append(discord.SelectOption(label=label, emoji=emoji))
        self.add_item(CategorySelect(options))

class CategorySelect(ui.Select):
    def __init__(self, options):
        super().__init__(placeholder="カテゴリーを選択してください", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        await interaction.response.send_message(f"✅ カテゴリー「{selected}」でチケットを作成します（仮処理）", ephemeral=True)

# --- ロール付与ボタンビュー ---
class RoleButtonView(ui.View):
    def __init__(self, role: discord.Role):
        super().__init__(timeout=None)
        self.role = role

    @ui.button(label="ロールを取得", style=discord.ButtonStyle.primary)
    async def role_button(self, interaction: discord.Interaction, button: ui.Button):
        member = interaction.user
        if self.role in member.roles:
            await interaction.response.send_message(f"あなたはすでに「{self.role.name}」のロールを持っています。", ephemeral=True)
            return
        try:
            await member.add_roles(self.role)
            await interaction.response.send_message(f"✅ 「{self.role.name}」のロールを付与しました！", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("⚠️ ロールを付与する権限がありません。", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"⚠️ エラーが発生しました: {e}", ephemeral=True)

# --- Webサーバー（Render用） ---
async def health_check(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    port = int(os.environ.get('PORT', 5000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"Web server started on port {port}")

# --- コマンド群 ---

# 実績投稿チャンネル設定（管理者限定）
@bot.tree.command(name="achievement_channel", description="実績投稿チャンネルを設定")
@app_commands.describe(channel="実績投稿チャンネルに設定するテキストチャンネル")
@app_commands.checks.has_permissions(administrator=True)
async def achievement_channel_set(interaction: discord.Interaction, channel: discord.TextChannel):
    guild_id = interaction.guild.id
    c.execute("""
    INSERT INTO achievement_channels (guild_id, channel_id)
    VALUES (?, ?)
    ON CONFLICT(guild_id) DO UPDATE SET channel_id=excluded.channel_id
    """, (guild_id, channel.id))
    conn.commit()
    await interaction.response.send_message(f"✅ 実績投稿チャンネルを {channel.mention} に設定しました。", ephemeral=True)

# 実績投稿コマンド
@bot.tree.command(name="write_achievement", description="実績を投稿します")
@app_commands.describe(
    user_id="実績記入者のユーザーID（数字）",
    achievement="実績内容",
    comment="コメント",
    rating="評価（1〜5）"
)
async def write_achievement(interaction: discord.Interaction,
                            user_id: str,
                            achievement: str,
                            comment: str,
                            rating: app_commands.Range[int, 1, 5]):
    if not user_id.isdigit():
        await interaction.response.send_message("⚠️ ユーザーIDは数字で入力してください。", ephemeral=True)
        return

    c.execute("SELECT channel_id FROM achievement_channels WHERE guild_id = ?", (interaction.guild.id,))
    row = c.fetchone()
    if not row:
        await interaction.response.send_message("⚠️ 実績投稿チャンネルが設定されていません。", ephemeral=True)
        return
    channel = interaction.guild.get_channel(row[0])
    if not channel:
        await interaction.response.send_message("⚠️ 実績投稿チャンネルが見つかりません。", ephemeral=True)
        return

    embed = discord.Embed(title="🎉 新しい実績が届きました！", color=discord.Color.gold())
    embed.add_field(name="記入者（ユーザーID）", value=user_id, inline=False)
    embed.add_field(name="実績内容", value=achievement, inline=False)
    embed.add_field(name="コメント", value=comment, inline=False)
    embed.add_field(name="評価", value=f"{rating} / 5", inline=False)

    try:
        await channel.send(embed=embed)
        await interaction.response.send_message("✅ 実績を投稿しました！", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("⚠️ 実績投稿チャンネルへの送信権限がありません。", ephemeral=True)

# カテゴリー作成コマンド（管理者限定）
@bot.tree.command(name="category_create", description="カテゴリーを作成します")
@app_commands.describe(name="カテゴリー名", emoji="カテゴリーの絵文字（任意）")
@app_commands.checks.has_permissions(administrator=True)
async def category_create(interaction: discord.Interaction, name: str, emoji: str = None):
    guild_id = interaction.guild.id
    if guild_id not in categories:
        categories[guild_id] = {}

    new_id = max(categories[guild_id].keys(), default=0) + 1
    categories[guild_id][new_id] = {"name": name, "emoji": emoji}

    await interaction.response.send_message(f"✅ カテゴリー「{name}」を作成しました。", ephemeral=True)

# カテゴリー削除コマンド（管理者限定・選択型）
@bot.tree.command(name="category_delete", description="カテゴリーを削除します")
@app_commands.checks.has_permissions(administrator=True)
async def category_delete(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    if guild_id not in categories or not categories[guild_id]:
        await interaction.response.send_message("⚠️ 削除できるカテゴリーがありません。", ephemeral=True)
        return

    options = [
        discord.SelectOption(
            label=cat["name"],
            emoji=cat["emoji"],
            value=str(cat_id)
        )
        for cat_id, cat in categories[guild_id].items()
    ]

    class DeleteCategoryView(ui.View):
        @ui.select(
            placeholder="削除するカテゴリーを選択してください",
            options=options
        )
        async def select_callback(self, interaction2: discord.Interaction, select: ui.Select):
            cat_id = int(select.values[0])
            cat_name = categories[guild_id][cat_id]["name"]
            del categories[guild_id][cat_id]
            await interaction2.response.edit_message(content=f"✅ カテゴリー「{cat_name}」を削除しました。", view=None)

    view = DeleteCategoryView()
    await interaction.response.send_message("🗑️ 削除するカテゴリーを選択してください。", view=view, ephemeral=True)

# チケットパネル作成コマンド
@bot.tree.command(name="maketike_panel", description="チケットパネルを作るゾ")
@app_commands.describe(title="パネルのタイトル", description="パネルの説明")
async def ticket_panel(interaction: discord.Interaction, title: str, description: str):
    guild_id = interaction.guild.id
    if guild_id not in categories or not categories[guild_id]:
        await interaction.response.send_message("⚠️ カテゴリーが設定されていません。", ephemeral=True)
        return

    embed = discord.Embed(title=title, description=description)
    cats = [ {"name": v["name"], "emoji": v["emoji"]} for v in categories[guild_id].values() ]
    await interaction.response.send_message(embed=embed, view=TicketView(cats))

# 埋め込みメッセージ送信コマンド
@bot.tree.command(name="send_embed", description="埋め込みめっせを送れるゾ")
@app_commands.describe(
    title="タイトル",
    description="説明文",
    emojis="表示したい絵文字をカンマ区切りで入力（任意）")
async def send_embed(interaction: discord.Interaction, title: str, description: str, emojis: str = None):
    emoji_text = ""
    if emojis:
        emoji_list = [e.strip() for e in emojis.split(",") if e.strip()]
        emoji_text = " ".join(emoji_list)

    embed = discord.Embed(title=f"{emoji_text} {title}".strip(), description=description)
    await interaction.response.send_message(embed=embed)

# ロール付与パネル作成コマンド
@bot.tree.command(name="verify_panel", description="埋め込み型で認証パネル作るゾ")
@app_commands.describe(
    title="パネルのタイトル",
    description="パネルの説明",
    role="付与するロール",
    emoji="パネルタイトルの前につける絵文字（Discord内絵文字OK）"
)
async def role_panel(interaction: discord.Interaction, title: str, description: str, role: discord.Role, emoji: str = None):
    embed_title = f"{emoji} {title}".strip() if emoji else title
    embed = discord.Embed(title=embed_title, description=description, color=discord.Color.blurple())
    view = RoleButtonView(role)
    await interaction.response.send_message(embed=embed, view=view)

# ランダムで10個のユーザーIDを取得するコマンド（コピー可能なコードブロック表示）
@bot.tree.command(name="random_gift", description="必ず入ってるギフトリンクを受け取れるゾ🎁")
async def random_users(interaction: discord.Interaction):
    members = [member for member in interaction.guild.members if not member.bot]
    if not members:
        await interaction.response.send_message("⚠️ メンバーが見つかりません。", ephemeral=True)
        return

    random.shuffle(members)
    selected = members[:10]
    user_ids = "\n".join([f"`{member.id}`" for member in selected])

    await interaction.response.send_message(f"🎲 ランダムなユーザーID:\n{user_ids}", ephemeral=True)

# --- Bot起動 ---
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands.")
    except Exception as e:
        print(f"Sync failed: {e}")

async def main():
    # Webサーバーを開始
    await start_web_server()
    
    # Botを開始
    token = os.environ.get('DISCORD_TOKEN')
    if not token:
        print("Error: DISCORD_TOKEN environment variable not set")
        return
    
    async with bot:
        await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())
