
# --- ライブラリ ---
import discord
from discord.ext import commands
from discord import app_commands, ui
from flask import Flask
import json
import threading
import random
import os

# --- データファイルパス ---
ACHIEVEMENT_CHANNELS_FILE = "achievement_channels.json"
CATEGORIES_FILE = "categories.json"

# --- データ管理関数 ---
def load_json_file(filename, default=None):
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default or {}

def save_json_file(filename, data):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def save_achievement_channel(guild_id, channel_id):
    data = load_json_file(ACHIEVEMENT_CHANNELS_FILE, {})
    data[str(guild_id)] = channel_id
    save_json_file(ACHIEVEMENT_CHANNELS_FILE, data)

def get_achievement_channel(guild_id):
    data = load_json_file(ACHIEVEMENT_CHANNELS_FILE, {})
    return data.get(str(guild_id))

def save_category(guild_id, name, emoji):
    data = load_json_file(CATEGORIES_FILE, {})
    guild_key = str(guild_id)
    if guild_key not in data:
        data[guild_key] = []
    
    # 既存のカテゴリーを更新または新規追加
    for i, cat in enumerate(data[guild_key]):
        if cat["name"] == name:
            data[guild_key][i] = {"name": name, "emoji": emoji}
            break
    else:
        data[guild_key].append({"name": name, "emoji": emoji})
    
    save_json_file(CATEGORIES_FILE, data)

def delete_category_db(guild_id, name):
    data = load_json_file(CATEGORIES_FILE, {})
    guild_key = str(guild_id)
    if guild_key in data:
        data[guild_key] = [cat for cat in data[guild_key] if cat["name"] != name]
        save_json_file(CATEGORIES_FILE, data)

def load_categories(guild_id):
    data = load_json_file(CATEGORIES_FILE, {})
    # レガシー形式（配列）の場合は新形式に変換
    if isinstance(data, list):
        # 配列形式のデータを新形式に変換して保存
        new_data = {str(guild_id): data}
        save_json_file(CATEGORIES_FILE, new_data)
        return data
    return data.get(str(guild_id), [])

# --- Flask アプリケーション設定 ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Discord Bot is running!"

@app.route('/status')
def status():
    return {"status": "online", "bot": str(bot.user) if bot.user else "offline"}

# --- Bot初期化 ---
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# --- チケット UI ---
class CategorySelect(ui.Select):
    def __init__(self, options):
        super().__init__(placeholder="カテゴリーを選択してください", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        guild = interaction.guild
        user = interaction.user

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(view_channel=True),
        }

        for role in guild.roles:
            if role.permissions.administrator:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        channel_name = f"ticket-{user.name}-{random.randint(1000, 9999)}"
        ticket_ch = await guild.create_text_channel(channel_name, overwrites=overwrites)

        await ticket_ch.send(
            f"✅ {user.mention} さんのチケットです。カテゴリー: **{selected}**",
            view=DeleteTicketView()
        )
        await interaction.response.send_message(f"✅ カテゴリー「{selected}」でチケットを作成しました！", ephemeral=True)

class TicketView(ui.View):
    def __init__(self, categories_data):
        super().__init__(timeout=None)
        options = [discord.SelectOption(label=cat["name"], emoji=cat["emoji"]) for cat in categories_data]
        self.add_item(CategorySelect(options))

class DeleteTicketView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="🗑️ チケットを削除", style=discord.ButtonStyle.danger)
    async def delete_ticket(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.channel.delete()
        await interaction.response.send_message("✅ チケットを削除しました。", ephemeral=True)

# --- カテゴリー削除 UI ---
class DeleteCategorySelect(ui.Select):
    def __init__(self, options, guild_id):
        super().__init__(placeholder="削除するカテゴリーを選択", min_values=1, max_values=1, options=options)
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        delete_category_db(self.guild_id, selected)
        await interaction.response.send_message(f"✅ カテゴリー **{selected}** を削除しました。", ephemeral=True)

class DeleteCategoryView(ui.View):
    def __init__(self, categories_data, guild_id):
        super().__init__(timeout=60)
        options = [discord.SelectOption(label=cat["name"], emoji=cat["emoji"]) for cat in categories_data]
        self.add_item(DeleteCategorySelect(options, guild_id))

# --- ロールボタン UI ---
class RoleButtonView(ui.View):
    def __init__(self, role: discord.Role):
        super().__init__(timeout=None)
        self.role = role

    @ui.button(label="ロールを取得", style=discord.ButtonStyle.primary)
    async def role_button(self, interaction: discord.Interaction, button: ui.Button):
        member = interaction.user
        if self.role in member.roles:
            await interaction.response.send_message(f"すでに「{self.role.name}」ロールを持っています。", ephemeral=True)
        else:
            try:
                await member.add_roles(self.role)
                await interaction.response.send_message(f"✅ 「{self.role.name}」を付与しました！", ephemeral=True)
            except Exception as e:
                await interaction.response.send_message(f"⚠️ エラー: {e}", ephemeral=True)

# --- スラッシュコマンド定義 ---
@bot.tree.command(name="achievement_channel", description="実績投稿チャンネルを設定")
@app_commands.checks.has_permissions(administrator=True)
async def achievement_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    try:
        save_achievement_channel(interaction.guild.id, channel.id)
        await interaction.response.send_message(f"✅ 実績投稿チャンネルを {channel.mention} に設定しました。", ephemeral=True)
    except Exception as e:
        print(f"エラー: {e}")
        await interaction.response.send_message("⚠️ エラーが発生しました。", ephemeral=True)

@bot.tree.command(name="write_achievement", description="実績を投稿します")
@app_commands.describe(
    user_id="記録者のユーザーID（数字）",
    achievement="実績内容",
    comment="コメント",
    rating="評価（1〜5）"
)
async def write_achievement(interaction: discord.Interaction, user_id: str, achievement: str, comment: str, rating: app_commands.Range[int, 1, 5]):
    if not user_id.isdigit():
        return await interaction.response.send_message("⚠️ ユーザーIDは数字で入力してください。", ephemeral=True)

    try:
        channel_id = get_achievement_channel(interaction.guild.id)
        if not channel_id:
            return await interaction.response.send_message("⚠️ 実績投稿チャンネルが未設定です。", ephemeral=True)

        tgt = interaction.guild.get_channel(channel_id)
        if not tgt:
            return await interaction.response.send_message("⚠️ チャンネルが見つかりません。", ephemeral=True)

        embed = discord.Embed(title="🎉 新しい実績", color=discord.Color.gold())
        embed.add_field(name="記入者ID", value=user_id, inline=False)
        embed.add_field(name="内容", value=achievement, inline=False)
        embed.add_field(name="コメント", value=comment, inline=False)
        embed.add_field(name="評価", value=f"{rating}/5", inline=False)

        await tgt.send(embed=embed)
        await interaction.response.send_message("✅ 実績を投稿しました！", ephemeral=True)
    except Exception as e:
        print(f"エラー: {e}")
        await interaction.response.send_message("⚠️ エラーが発生しました。", ephemeral=True)

@bot.tree.command(name="create_category", description="チケットカテゴリーを作成します")
async def create_category(interaction: discord.Interaction, name: str, emoji: str):
    save_category(interaction.guild.id, name, emoji)
    await interaction.response.send_message(f"✅ カテゴリー **{emoji} {name}** を作成しました！", ephemeral=True)

@bot.tree.command(name="delete_category", description="チケットカテゴリーを選択して削除します")
async def delete_category(interaction: discord.Interaction):
    categories_data = load_categories(interaction.guild.id)
    if not categories_data:
        await interaction.response.send_message("⚠️ カテゴリーが存在しません。", ephemeral=True)
        return
    view = DeleteCategoryView(categories_data, interaction.guild.id)
    await interaction.response.send_message(
        embed=discord.Embed(title="🗑️ カテゴリー削除", description="削除するカテゴリーを選択してください。"),
        view=view,
        ephemeral=True
    )

@bot.tree.command(name="ticket_panel", description="チケットパネルを作成します")
async def ticket_panel(interaction: discord.Interaction, title: str, description: str, image_url: str = None):
    categories_data = load_categories(interaction.guild.id)
    if not categories_data:
        return await interaction.response.send_message("⚠️ カテゴリーが登録されていません。", ephemeral=True)

    embed = discord.Embed(title=title, description=description)
    if image_url:
        embed.set_image(url=image_url)
    await interaction.response.send_message(embed=embed, view=TicketView(categories_data))

@bot.tree.command(name="verify", description="認証用ロールパネルを配置")
async def verify_panel(interaction: discord.Interaction, title: str, description: str, role: discord.Role, emoji: str = None):
    full_title = f"{emoji} {title}" if emoji else title
    await interaction.response.send_message(embed=discord.Embed(title=full_title, description=description), view=RoleButtonView(role))

@bot.tree.command(name="discordacounts", description="チケットに他人を招待")
async def ticket_permission(interaction: discord.Interaction, user: discord.Member):
    await interaction.channel.set_permissions(user, view_channel=True, send_messages=True)
    await interaction.response.send_message(f"✅ {user.mention} にチケット閲覧権限を付与しました！", ephemeral=True)

@bot.tree.command(name="send_embed", description="埋め込みメッセージを送信")
async def send_embed(interaction: discord.Interaction, title: str, description: str, emojis: str = None):
    emoji_text = " ".join([e.strip() for e in (emojis or "").split(",") if e.strip()])
    await interaction.response.send_message(embed=discord.Embed(title=f"{emoji_text} {title}".strip(), description=description))

@bot.tree.command(name="nitropresent", description="ニトロプレゼント風ID表示")
async def random_ids(interaction: discord.Interaction):
    members = [m for m in interaction.guild.members if not m.bot]
    if not members:
        return await interaction.response.send_message("⚠️ メンバーがいません。", ephemeral=True)
    random.shuffle(members)
    out = "\n".join(f"`{m.id}`" for m in members[:25])
    await interaction.response.send_message(f"🎲 ランダムなユーザーID:\n{out}", ephemeral=True)

@bot.tree.command(name='achievement_panel', description='実績記入パネルを送信します')
async def achievement_panel(interaction: discord.Interaction):
    embed = discord.Embed(
        title='🎖️ 実績パネル',
        description=(
            '以下のテンプレートをコピーしてメッセージ編集で記入してください。\n\n'
            '```\n'
            '【記入者】<@ユーザーID>\n'
            '【実績内容】ここに実績内容を入力\n'
            '【コメント】ここにコメントを入力\n'
            '【評価】1〜5\n'
            '```\n'
        ),
        color=discord.Color.gold()
    )
    embed.set_footer(text='必要に応じてメッセージを編集してください。')
    await interaction.response.send_message(embed=embed)

# --- 起動処理 ---
@bot.event
async def on_ready():
    print(f"✅ ログイン完了：{bot.user}（ID: {bot.user.id}）")
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} コマンドを同期しました。")
    except Exception as e:
        print("⚠️ コマンド同期失敗:", e)

# --- Flaskサーバーの実行関数 ---
def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)

# --- 実行部分（最後） ---
if __name__ == "__main__":
    # Flaskサーバーを別スレッドで起動
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # Discordボットを起動（環境変数からトークンを取得）
    bot_token = os.environ.get('DISCORD_TOKEN')
    if not bot_token:
        print("⚠️ エラー: DISCORD_TOKEN環境変数が設定されていません")
        exit(1)
    
    bot.run(bot_token)
