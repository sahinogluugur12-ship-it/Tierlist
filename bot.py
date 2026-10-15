import discord
from discord import app_commands
from discord.ext import commands
import json
import asyncio
import os
from datetime import datetime

# ─── Config Yükle ───────────────────────────────────────────────
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    config = json.load(f)

TOKEN = config["token"]
GUILD_ID = discord.Object(id=int(config["guild_id"]))
TIER_RESULT_CHANNEL_ID = int(config["tier_result_channel_id"])
YETKILI_ROLE_ID = int(config["yetkili_role_id"])
SERVER_NAME = config.get("server_name", "mc.rushcraft.net")
EMBED_COLOR = int(config.get("embed_color", "0x2b2d31"), 16)
KATEGORILER = config.get("kategoriler", ["TrapPvP", "ElytraPvP"])
TIERLER = config.get("tierler", ["LT1", "LT2", "LT3", "LT4", "LT5", "HT1", "HT2", "HT3", "HT4", "HT5"])
SIRA_KANALLARI = config.get("sira_kanallari", {})

DATA_FILE = os.path.join(os.path.dirname(__file__), "queue_data.json")

# ─── Veri Saklama ───────────────────────────────────────────────
# Yapı:
# {
#   "TrapPvP": {
#       "is_open": True,
#       "message_id": 123456,
#       "channel_id": 123456,
#       "list": [
#           {"user_id": 111, "mc_name": "Enes", "server": "mc.rushcraft.net", "status": "waiting", "ticket_id": None}
#       ]
#   }
# }

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    # Varsayılan veri
    data = {}
    for kat in SIRA_KANALLARI.keys():
        data[kat] = {
            "is_open": True,
            "message_id": None,
            "channel_id": int(SIRA_KANALLARI[kat]),
            "list": []
        }
    return data

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

db = load_data()

# Eksik kategoriler varsa ekle
for kat in SIRA_KANALLARI.keys():
    if kat not in db:
        db[kat] = {
            "is_open": True,
            "message_id": None,
            "channel_id": int(SIRA_KANALLARI[kat]),
            "list": []
        }
save_data(db)

import ssl
import aiohttp

try:
    ssl._create_default_https_context = ssl._create_unverified_context
except Exception:
    pass

# ─── Bot Başlatma ────────────────────────────────────────────────
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)


def is_tester_or_admin(member: discord.Member) -> bool:
    if not isinstance(member, discord.Member):
        return False
    # Sunucu sahibi veya Yönetici izni olanlar
    if member.guild_permissions.administrator or member.id == member.guild.owner_id:
        return True

    guild_id = member.guild.id
    # YETKILI_ROLE_ID eğer @everyone (sunucu ID) değilse kontrol et
    if YETKILI_ROLE_ID != guild_id and any(r.id == YETKILI_ROLE_ID for r in member.roles):
        return True

    # Rol adında tester geçen roller (@everyone rolü hariç)
    for r in member.roles:
        if r.id == guild_id or r.is_default():
            continue
        r_name = r.name.lower()
        if "tester" in r_name:
            return True

    return False


def build_queue_embed(kategori: str) -> discord.Embed:
    kat_data = db.get(kategori, {"is_open": True, "list": []})
    is_open = kat_data.get("is_open", True)
    q_list = kat_data.get("list", [])

    if not is_open:
        embed = discord.Embed(
            title=f"🔒 {kategori} - Sıra Şu Anda Kapalı",
            description=(
                "🔴 **Bu kategori için tier test başvuruları yetkililer tarafından kapatılmıştır.**\n\n"
                "⏳ Lütfen sıranın tekrar açılmasını bekleyiniz.\n"
                "*(Sıra açıldığında bu mesaj otomatik güncellenecek ve 'Sıraya Katıl' butonu gelecektir.)*"
            ),
            color=0xED4245,
            timestamp=datetime.now()
        )
        embed.set_footer(text=f"{SERVER_NAME} • Tier Sistemi")
        return embed

    status_str = "🟢 **AÇIK**"
    lines = []
    if not q_list:
        lines.append("*Şu anda sırada kimse yok.*")
    else:
        for i, item in enumerate(q_list, 1):
            user_mention = f"<@{item['user_id']}>"
            mc_name = item.get("mc_name", "Bilinmiyor")
            status = item.get("status", "waiting")
            
            if status == "testing":
                state_badge = "⚔️ **Test Ediliyor...**"
            else:
                state_badge = "⏳ Bekliyor"
                
            lines.append(f"**{i})** {user_mention} — `{mc_name}` | {state_badge}")

    embed = discord.Embed(
        title=f"⚔️ {kategori} - Tier Test Sırası",
        description=(
            f"**Sıra Durumu:** {status_str}\n"
            f"**Toplam Bekleyen:** `{len(q_list)}` kişi\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            + "\n".join(lines) +
            "\n━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=0x2b2d31,
        timestamp=datetime.now()
    )
    embed.set_footer(text=f"{SERVER_NAME} • Tier Sistemi")
    return embed


async def update_queue_message(kategori: str):
    """Sıra kanalındaki mesajı canlı günceller."""
    kat_data = db.get(kategori)
    if not kat_data:
        return

    ch_id = kat_data.get("channel_id")
    msg_id = kat_data.get("message_id")
    is_open = kat_data.get("is_open", True)
    if not ch_id:
        return

    channel = bot.get_channel(int(ch_id))
    if not channel:
        return

    embed = build_queue_embed(kategori)
    # Sıra kapalıysa butonları TAMAMEN kaldır (view=None)
    view = QueueControlView(kategori) if is_open else None

    if msg_id:
        try:
            msg = await channel.fetch_message(int(msg_id))
            await msg.edit(embed=embed, view=view)
            return
        except discord.NotFound:
            pass
        except Exception as e:
            print(f"Mesaj güncelleme hatası: {e}")

    # Mesaj bulunamadıysa yeni gönder ve ID kaydet
    try:
        new_msg = await channel.send(embed=embed, view=view)
        kat_data["message_id"] = new_msg.id
        save_data(db)
    except Exception as e:
        print(f"Yeni mesaj gönderme hatası: {e}")


# ═══════════════════════════════════════════════════════════════
#                    MODAL - OYUNCU BİLGİ ALMA
# ═══════════════════════════════════════════════════════════════
class JoinQueueModal(discord.ui.Modal):
    def __init__(self, kategori: str):
        super().__init__(title=f"{kategori} - Sıraya Katıl")
        self.kategori = kategori

        self.mc_name = discord.ui.TextInput(
            label="Minecraft Oyuncu İsmin",
            placeholder="Örn: enes_developer",
            required=True,
            max_length=32
        )
        self.server_name = discord.ui.TextInput(
            label="Hangi Sunucu?",
            placeholder="Örn: mc.rushcraft.net",
            default=SERVER_NAME,
            required=True,
            max_length=64
        )
        self.add_item(self.mc_name)
        self.add_item(self.server_name)

    async def on_submit(self, interaction: discord.Interaction):
        kat_data = db.get(self.kategori)
        if not kat_data or not kat_data.get("is_open", True):
            await interaction.response.send_message("❌ Bu sıra şu an kapalıdır!", ephemeral=True)
            return

        # Zaten bu veya başka bir sırada var mı?
        user_id = interaction.user.id
        for k_name, k_info in db.items():
            for item in k_info.get("list", []):
                if item["user_id"] == user_id:
                    await interaction.response.send_message(
                        f"⚠️ Zaten **{k_name}** sırasında varsın! Önce sıranın bitmesini bekle.",
                        ephemeral=True
                    )
                    return

        kat_data["list"].append({
            "user_id": user_id,
            "mc_name": self.mc_name.value.strip(),
            "server": self.server_name.value.strip(),
            "status": "waiting",
            "ticket_id": None
        })
        save_data(db)

        sira_no = len(kat_data["list"])
        await interaction.response.send_message(
            f"✅ **{self.kategori}** sırasına başarıyla eklendin! Sıra Numaran: **#{sira_no}**",
            ephemeral=True
        )

        await update_queue_message(self.kategori)


# ═══════════════════════════════════════════════════════════════
#               BUTONLAR - SIRA KONTROL PANELİ
# ═══════════════════════════════════════════════════════════════
class QueueControlView(discord.ui.View):
    def __init__(self, kategori: str):
        super().__init__(timeout=None)
        self.kategori = kategori

        # Katıl Butonu
        join_btn = discord.ui.Button(
            label="Sıraya Katıl",
            style=discord.ButtonStyle.green,
            emoji="🎮",
            custom_id=f"btn_join_{kategori}"
        )
        join_btn.callback = self.join_callback
        self.add_item(join_btn)

        # Ayrıl Butonu
        leave_btn = discord.ui.Button(
            label="Sıradan Ayrıl",
            style=discord.ButtonStyle.red,
            emoji="🚪",
            custom_id=f"btn_leave_{kategori}"
        )
        leave_btn.callback = self.leave_callback
        self.add_item(leave_btn)

        # Tester Test Al Butonu
        test_btn = discord.ui.Button(
            label="Test Al (1. Sıra)",
            style=discord.ButtonStyle.blurple,
            emoji="⚔️",
            custom_id=f"btn_test_{kategori}"
        )
        test_btn.callback = self.test_callback
        self.add_item(test_btn)

    async def join_callback(self, interaction: discord.Interaction):
        kat_data = db.get(self.kategori)
        if not kat_data or not kat_data.get("is_open", True):
            await interaction.response.send_message("❌ Bu sıra şu an kapalıdır! Başvuru alınmıyor.", ephemeral=True)
            return

        user_id = interaction.user.id
        for k_name, k_info in db.items():
            for item in k_info.get("list", []):
                if item["user_id"] == user_id:
                    await interaction.response.send_message(
                        f"⚠️ Zaten **{k_name}** sırasında varsın! Sıranın bitmesini bekle veya 'Sıradan Ayrıl' butonuna bas.",
                        ephemeral=True
                    )
                    return

        await interaction.response.send_modal(JoinQueueModal(self.kategori))

    async def leave_callback(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        removed_from = []
        for k_name, k_info in db.items():
            q_list = k_info.get("list", [])
            initial_len = len(q_list)
            for item in q_list:
                if item["user_id"] == user_id and item.get("ticket_id"):
                    t_ch = interaction.guild.get_channel(int(item["ticket_id"]))
                    if t_ch:
                        asyncio.create_task(t_ch.delete())
            k_info["list"] = [x for x in q_list if x["user_id"] != user_id]
            if len(k_info["list"]) < initial_len:
                removed_from.append(k_name)

        if removed_from:
            save_data(db)
            for k in removed_from:
                await update_queue_message(k)
            await interaction.response.send_message(f"✅ Sıradan başarıyla ayrıldın (**{', '.join(removed_from)}**).", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Zaten sırada değilsin.", ephemeral=True)

    async def test_callback(self, interaction: discord.Interaction):
        # Tester yetki kontrolü
        if not isinstance(interaction.user, discord.Member) or not is_tester_or_admin(interaction.user):
            await interaction.response.send_message("❌ Bu butonu sadece Tester ve Yetkililer kullanabilir!", ephemeral=True)
            return

        kat_data = db.get(self.kategori)
        q_list = kat_data.get("list", []) if kat_data else []
        if not q_list:
            await interaction.response.send_message("❌ Sırada bekleyen kimse yok!", ephemeral=True)
            return

        first_player = q_list[0]
        if first_player.get("status") == "testing":
            await interaction.response.send_message(
                f"⚠️ 1. sıradaki oyuncu zaten şu an test ediliyor! (Ticket ID: <#{first_player.get('ticket_id')}>)",
                ephemeral=True
            )
            return

        # 1. sıradaki oyuncuyu al ve ticket aç
        guild = interaction.guild
        player_member = guild.get_member(first_player["user_id"])
        if not player_member:
            # Oyuncu sunucudan çıkmışsa sıradan at
            kat_data["list"].pop(0)
            save_data(db)
            await interaction.response.send_message("⚠️ 1. sıradaki oyuncu sunucuda bulunamadığı için sıradan çıkarıldı.", ephemeral=True)
            await update_queue_message(self.kategori)
            return

        await interaction.response.defer(ephemeral=True)

        # Ticket kanalı oluştur
        mc_clean = "".join(c for c in first_player["mc_name"].lower() if c.isalnum() or c in "-_")
        channel_name = f"test-{mc_clean}"

        # İzinler: Sadece Tester ve Test Edilen Oyuncu görebilir!
        overwrites = {
            # Herkese tamamen kapat
            guild.default_role: discord.PermissionOverwrite(view_channel=False, read_messages=False, send_messages=False),
            # Botun kendisi
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True, attach_files=True, read_message_history=True, manage_channels=True),
            # Testi açan yetkili (Tester)
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, read_message_history=True, manage_channels=True),
            # Sadece testi açılan oyuncu
            player_member: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, read_message_history=True)
        }

        # Tester rolüne izin ver (Eğer @everyone değilse)
        tester_role = guild.get_role(YETKILI_ROLE_ID)
        if tester_role and tester_role.id != guild.id and not tester_role.is_default():
            overwrites[tester_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, read_message_history=True)

        # İsmi "tester" içeren tüm yetkili rollerine izin ver
        for r in guild.roles:
            if r.id != guild.id and not r.is_default() and "tester" in r.name.lower():
                overwrites[r] = discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, read_message_history=True)

        # Eski test edilenlerin (Tier rolleri) ve Üye rolünün görmesini KESİNLİKLE engelle
        for r in guild.roles:
            if r.id == guild.id or r.is_default():
                continue
            r_name = r.name.upper()
            if "ÜYE" in r_name or "MEMBER" in r_name or any(t in r_name for t in ["LT1", "LT2", "LT3", "LT4", "LT5", "HT1", "HT2", "HT3", "HT4", "HT5"]):
                overwrites[r] = discord.PermissionOverwrite(view_channel=False, read_messages=False, send_messages=False)


        try:
            category_parent = interaction.channel.category if interaction.channel else None
            ticket_channel = await guild.create_text_channel(
                name=channel_name,
                overwrites=overwrites,
                category=category_parent,
                topic=f"Tier Test Ticket | Oyuncu: {player_member.mention} | Kategori: {self.kategori}"
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Ticket kanalı açılırken hata oluştu: {e}", ephemeral=True)
            return

        first_player["status"] = "testing"
        first_player["ticket_id"] = ticket_channel.id
        save_data(db)

        # Ticket kanalına karşılama mesajı at
        ticket_embed = discord.Embed(
            title=f"⚔️ {self.kategori} Tier Testi Başladı!",
            description=(
                f"**Tester:** {interaction.user.mention}\n"
                f"**Oyuncu:** {player_member.mention} (`{first_player['mc_name']}`)\n"
                f"**Sunucu:** `{first_player.get('server', SERVER_NAME)}`\n\n"
                "📌 **Tester Bilgilendirme:**\n"
                "Test bittiğinde aşağıdaki **Açılır Menüden** verilecek Tier'ı seçin ve skoru yazın.\n"
                "*(Tier verildiğinde sonuç otomatik kanala atılır, rol verilir ve bu oda kapanır.)*"
            ),
            color=0x57F287,
            timestamp=datetime.now()
        )
        ticket_view = TicketControlView(self.kategori, first_player["user_id"])
        await ticket_channel.send(content=f"{player_member.mention} {interaction.user.mention}", embed=ticket_embed, view=ticket_view)

        await interaction.followup.send(f"✅ Test başlatıldı! Kanal: {ticket_channel.mention}", ephemeral=True)
        await update_queue_message(self.kategori)


# ═══════════════════════════════════════════════════════════════
#          TICKET İÇİNDEKİ HIZLI TIER MENÜSÜ & SKOR FORMU
# ═══════════════════════════════════════════════════════════════
class TicketScoreModal(discord.ui.Modal):
    def __init__(self, kategori: str, user_id: int, selected_tier: str):
        super().__init__(title=f"Skor Gir: {selected_tier[:25]}")
        self.kategori = kategori
        self.user_id = user_id
        self.selected_tier = selected_tier

        self.score_input = discord.ui.TextInput(
            label="Skor (Örn: 2-0)",
            placeholder="Örn: 2-0 veya 3-1",
            required=True,
            max_length=15,
            default="2-0"
        )
        self.add_item(self.score_input)

    async def on_submit(self, interaction: discord.Interaction):
        # Discord'un 3 saniyelik zaman aşımına düşmesini önlemek için anında defer et!
        await interaction.response.defer(ephemeral=True)
        try:
            await process_tier_give(
                interaction=interaction,
                target_user_id=self.user_id,
                kategori=self.kategori,
                tier=self.selected_tier,
                skor=self.score_input.value.strip(),
                ticket_channel=interaction.channel
            )
        except Exception as e:
            print(f"❌ process_tier_give hatası: {e}")
            try:
                await interaction.followup.send(f"❌ Tier verilirken bir hata oluştu: {e}", ephemeral=True)
            except Exception:
                pass


class TierSelectMenu(discord.ui.Select):
    def __init__(self, kategori: str, user_id: int):
        self.kategori = kategori
        self.target_user_id = user_id

        # Kategoriye göre veya genel Trap / Ely seçenekleri
        options = [
            # TrapPvP Seçenekleri
            discord.SelectOption(label="LT1 [TrapPvP]", value="LT1 [TrapPvP]", emoji="🛡️"),
            discord.SelectOption(label="LT2 [TrapPvP]", value="LT2 [TrapPvP]", emoji="🛡️"),
            discord.SelectOption(label="LT3 [TrapPvP]", value="LT3 [TrapPvP]", emoji="🛡️"),
            discord.SelectOption(label="LT4 [TrapPvP]", value="LT4 [TrapPvP]", emoji="🛡️"),
            discord.SelectOption(label="LT5 [TrapPvP]", value="LT5 [TrapPvP]", emoji="🛡️"),
            discord.SelectOption(label="HT1 [TrapPvP]", value="HT1 [TrapPvP]", emoji="⚔️"),
            discord.SelectOption(label="HT2 [TrapPvP]", value="HT2 [TrapPvP]", emoji="⚔️"),
            discord.SelectOption(label="HT3 [TrapPvP]", value="HT3 [TrapPvP]", emoji="⚔️"),
            discord.SelectOption(label="HT4 [TrapPvP]", value="HT4 [TrapPvP]", emoji="⚔️"),
            discord.SelectOption(label="HT5 [TrapPvP]", value="HT5 [TrapPvP]", emoji="⚔️"),

            # ElyPvP Seçenekleri
            discord.SelectOption(label="LT1 [ElyPvP]", value="LT1 [ElyPvP]", emoji="🪽"),
            discord.SelectOption(label="LT2 [ElyPvP]", value="LT2 [ElyPvP]", emoji="🪽"),
            discord.SelectOption(label="LT3 [ElyPvP]", value="LT3 [ElyPvP]", emoji="🪽"),
            discord.SelectOption(label="LT4 [ElyPvP]", value="LT4 [ElyPvP]", emoji="🪽"),
            discord.SelectOption(label="LT5 [ElyPvP]", value="LT5 [ElyPvP]", emoji="🪽"),
            discord.SelectOption(label="HT1 [ElyPvP]", value="HT1 [ElyPvP]", emoji="✨"),
            discord.SelectOption(label="HT2 [ElyPvP]", value="HT2 [ElyPvP]", emoji="✨"),
            discord.SelectOption(label="HT3 [ElyPvP]", value="HT3 [ElyPvP]", emoji="✨"),
            discord.SelectOption(label="HT4 [ElyPvP]", value="HT4 [ElyPvP]", emoji="✨"),
            discord.SelectOption(label="HT5 [ElyPvP]", value="HT5 [ElyPvP]", emoji="✨"),
        ]

        super().__init__(
            placeholder="🏆 Verilecek Tier'ı Buradan Seç...",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
            custom_id=f"tier_select:{kategori}:{user_id}"
        )

    async def callback(self, interaction: discord.Interaction):
        # Tester yetki kontrolü
        if not is_tester_or_admin(interaction.user):
            await interaction.response.send_message("❌ Sadece Tester yetkilisi tier verebilir!", ephemeral=True)
            return

        selected_tier = self.values[0]
        # Skor sormak için modal aç
        await interaction.response.send_modal(TicketScoreModal(self.kategori, self.target_user_id, selected_tier))


class TicketControlView(discord.ui.View):
    def __init__(self, kategori: str, user_id: int):
        super().__init__(timeout=None)
        self.kategori = kategori
        self.user_id = user_id

        # Menüyü ekle
        self.add_item(TierSelectMenu(kategori, user_id))

        # Kapat Butonu
        close_btn = discord.ui.Button(
            label="Testi İptal Et / Kapat",
            style=discord.ButtonStyle.danger,
            emoji="🔒",
            row=1,
            custom_id=f"ticket_close:{kategori}:{user_id}"
        )
        close_btn.callback = self.close_callback
        self.add_item(close_btn)

    async def close_callback(self, interaction: discord.Interaction):
        if not is_tester_or_admin(interaction.user):
            await interaction.response.send_message("❌ Sadece Tester yetkilisi bu ticket'ı kapatabilir!", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        # Sıradan tamamen düşür
        kat_data = db.get(self.kategori)
        if kat_data:
            kat_data["list"] = [x for x in kat_data.get("list", []) if x["user_id"] != self.user_id]
            save_data(db)
            await update_queue_message(self.kategori)

        await interaction.followup.send("🔒 Test iptal edildi ve oyuncu sıradan çıkarıldı. Ticket siliniyor...", ephemeral=True)
        await asyncio.sleep(2)
        try:
            await interaction.channel.delete()
        except Exception:
            pass



# ═══════════════════════════════════════════════════════════════
#                    ORTAK TIER VERME MANTIĞI
# ═══════════════════════════════════════════════════════════════
async def process_tier_give(interaction: discord.Interaction, target_user_id: int, kategori: str, tier: str, skor: str, ticket_channel=None):
    guild = interaction.guild
    member = guild.get_member(target_user_id)

    kat_data = db.get(kategori)
    item_found = None

    if kat_data:
        q_list = kat_data.get("list", [])
        for i, item in enumerate(q_list):
            if item["user_id"] == target_user_id:
                item_found = q_list.pop(i)
                break
        save_data(db)

    mc_name = item_found.get("mc_name", member.display_name if member else "Bilinmiyor") if item_found else (member.display_name if member else "Bilinmiyor")
    server_addr = item_found.get("server", SERVER_NAME) if item_found else SERVER_NAME

    tier_input = tier.strip()
    if "[" in tier_input and "]" in tier_input:
        tier_display = tier_input
        tier_upper = tier_input.split("[")[0].strip().upper()
    else:
        tier_upper = tier_input.upper()
        tier_display = f"{tier_upper} [{kategori}]"
    now = datetime.now()
    tarih_str = now.strftime("%d.%m.%Y %H:%M")

    # Tam istenen tasarım formatı:
    embed = discord.Embed(
        description=(
            f"**• Oyuncu:** <@{target_user_id}>\n"
            f"**• Kategori:** `{kategori}`\n"
            f"**• Tier:** `{tier_display}`\n"
            f"**• Skor:** `{skor}`\n"
            f"**• Yetkili:** {interaction.user.mention}"
        ),
        color=EMBED_COLOR,
        timestamp=now
    )
    author_icon = member.display_avatar.url if member else interaction.user.display_avatar.url
    embed.set_author(name=f"{mc_name} – Test Sonucu", icon_url=author_icon)
    embed.set_thumbnail(url=author_icon)
    embed.set_footer(text=f"{server_addr} • {tarih_str}")

    # Sonuç kanalına at
    result_channel = bot.get_channel(TIER_RESULT_CHANNEL_ID)
    if result_channel:
        try:
            await result_channel.send(embed=embed)
        except discord.Forbidden:
            print("❌ UYARI: Sonuç kanalına (#test-sonuclari) mesaj atılamadı çünkü botun mesaj atma yetkisi yok!")

    # DM bildirim
    if member:
        try:
            dm_embed = discord.Embed(
                title="🏆 Tier Test Sonucun Açıklandı!",
                description=(
                    f"**Kategori:** `{kategori}`\n"
                    f"**Tier:** `{tier_display}`\n"
                    f"**Skor:** `{skor}`\n"
                    f"**Yetkili:** {interaction.user.display_name}\n\n"
                    f"Sonucunu tebrik ederiz!"
                ),
                color=0x57F287
            )
            await member.send(embed=dm_embed)
        except Exception:
            pass

    # ─── Otomatik Rol Verme ───
    assigned_role_msg = ""
    if member and guild:
        def clean_text(s: str) -> str:
            return "".join(c for c in s.lower() if c.isalnum())

        target_clean = clean_text(tier_display)       # örn: "lt5trappvp" veya "lt5elypvp"
        tier_only_clean = clean_text(tier_upper)      # örn: "lt5"
        target_role = None

        # 1. Öncelik: Tam temizlenmiş isim eşleşmesi (Örn: "・LT5[ElyPvP]" -> "lt5elypvp" == "lt5elypvp")
        for r in guild.roles:
            if clean_text(r.name) == target_clean:
                target_role = r
                break

        # 2. Öncelik: Hem tier hem kategori kısaltması içeren rol
        if not target_role:
            for r in guild.roles:
                r_c = clean_text(r.name)
                if tier_only_clean in r_c:
                    if ("ely" in target_clean and "ely" in r_c) or ("trap" in target_clean and "trap" in r_c):
                        target_role = r
                        break

        # 3. Öncelik: Yalnızca Tier adı eşleşen (Örn: "LT5")
        if not target_role:
            for r in guild.roles:
                if clean_text(r.name) == tier_only_clean:
                    target_role = r
                    break

        if target_role:
            try:
                # Eski tier rollerini temizle (aynı kategorideki)
                roles_to_remove = []
                for r in member.roles:
                    r_c = clean_text(r.name)
                    is_same_cat = ("ely" in target_clean and "ely" in r_c) or ("trap" in target_clean and "trap" in r_c)
                    has_tier = any(t.lower() in r_c for t in TIERLER)
                    if is_same_cat and has_tier and r.id != target_role.id:
                        roles_to_remove.append(r)
                if roles_to_remove:
                    await member.remove_roles(*roles_to_remove, reason="Tier güncellemesi")

                await member.add_roles(target_role, reason=f"Tier verildi: {tier_display}")
                assigned_role_msg = f"\n🎭 Rol verildi: **{target_role.name}**"
            except discord.Forbidden:
                assigned_role_msg = f"\n⚠️ Rol verilemedi: Botun rolü Discord rol listesinde **{target_role.name}** rolünün altında bulunuyor! Bot rolünü yukarı taşıyın."
            except Exception as e:
                print(f"Rol verme hatası: {e}")
        else:
            assigned_role_msg = f"\n*(Sunucuda `{tier_display}` adında bir rol bulunamadı)*"


    # Sıra listesini canlı güncelle! (1. sıradan çıktı, 2. olan 1. oldu)
    await update_queue_message(kategori)

    response_text = f"✅ **{mc_name}** oyuncusuna **{tier_display}** ({skor}) verildi! Sıradan düşürüldü.{assigned_role_msg}"
    if not interaction.response.is_done():
        await interaction.response.send_message(response_text, ephemeral=True)
    else:
        await interaction.followup.send(response_text, ephemeral=True)

    # SADECE botun açtığı özel ticket ise kapat (Genel kanallar, test-sonuclari, sira kanalları ASLA silinemez!)
    protected_channel_ids = [TIER_RESULT_CHANNEL_ID] + [int(cid) for cid in SIRA_KANALLARI.values()]
    if ticket_channel and isinstance(ticket_channel, discord.TextChannel):
        if ticket_channel.id not in protected_channel_ids and ticket_channel.topic and "Tier Test Ticket" in ticket_channel.topic:
            await ticket_channel.send("🎉 Test tamamlandı! Kanal 5 saniye içinde silinecektir...")
            await asyncio.sleep(5)
            try:
                await ticket_channel.delete()
            except Exception:
                pass


KATEGORI_CHOICES = [
    app_commands.Choice(name=k, value=k)
    for k in [
        "TrapPvP", "ElytraPvP", "SwordPvP", "AxePvP",
        "UHC", "BuildUHC", "SMP", "PotPvP", "DiamondPvP", "SoupPvP"
    ]
]

TIER_CHOICES = [
    # TrapPvP Tierleri
    app_commands.Choice(name="LT1 [TrapPvP]", value="LT1 [TrapPvP]"),
    app_commands.Choice(name="LT2 [TrapPvP]", value="LT2 [TrapPvP]"),
    app_commands.Choice(name="LT3 [TrapPvP]", value="LT3 [TrapPvP]"),
    app_commands.Choice(name="LT4 [TrapPvP]", value="LT4 [TrapPvP]"),
    app_commands.Choice(name="LT5 [TrapPvP]", value="LT5 [TrapPvP]"),
    app_commands.Choice(name="HT1 [TrapPvP]", value="HT1 [TrapPvP]"),
    app_commands.Choice(name="HT2 [TrapPvP]", value="HT2 [TrapPvP]"),
    app_commands.Choice(name="HT3 [TrapPvP]", value="HT3 [TrapPvP]"),
    app_commands.Choice(name="HT4 [TrapPvP]", value="HT4 [TrapPvP]"),
    app_commands.Choice(name="HT5 [TrapPvP]", value="HT5 [TrapPvP]"),
    # ElyPvP Tierleri
    app_commands.Choice(name="LT1 [ElyPvP]", value="LT1 [ElyPvP]"),
    app_commands.Choice(name="LT2 [ElyPvP]", value="LT2 [ElyPvP]"),
    app_commands.Choice(name="LT3 [ElyPvP]", value="LT3 [ElyPvP]"),
    app_commands.Choice(name="LT4 [ElyPvP]", value="LT4 [ElyPvP]"),
    app_commands.Choice(name="LT5 [ElyPvP]", value="LT5 [ElyPvP]"),
    app_commands.Choice(name="HT1 [ElyPvP]", value="HT1 [ElyPvP]"),
    app_commands.Choice(name="HT2 [ElyPvP]", value="HT2 [ElyPvP]"),
    app_commands.Choice(name="HT3 [ElyPvP]", value="HT3 [ElyPvP]"),
    app_commands.Choice(name="HT4 [ElyPvP]", value="HT4 [ElyPvP]"),
    app_commands.Choice(name="HT5 [ElyPvP]", value="HT5 [ElyPvP]"),
]

# ═══════════════════════════════════════════════════════════════
#                    SLASH KOMUTLARI
# ═══════════════════════════════════════════════════════════════

@bot.tree.command(name="sira-kur", description="Sıra kontrol panelini kanala kurar ve sırayı açar (Yetkili)")
@app_commands.describe(kategori="Hangi kategori için sıra paneli kurulacak?")
@app_commands.choices(kategori=KATEGORI_CHOICES)
@app_commands.default_permissions(administrator=True)
async def cmd_sira_kur(interaction: discord.Interaction, kategori: app_commands.Choice[str]):
    kat_adi = kategori.value
    kat_data = db.get(kat_adi, {})
    kat_data["channel_id"] = interaction.channel_id
    kat_data["is_open"] = True
    if "list" not in kat_data:
        kat_data["list"] = []
    db[kat_adi] = kat_data
    save_data(db)

    embed = build_queue_embed(kat_adi)
    view = QueueControlView(kat_adi)

    msg = await interaction.channel.send(embed=embed, view=view)
    kat_data["message_id"] = msg.id
    save_data(db)

    await interaction.response.send_message(f"✅ **{kat_adi}** sırası bu kanala başarıyla kuruldu ve açıldı!", ephemeral=True)


@bot.tree.command(name="sirakur", description="Sıra kontrol panelini kanala kurar ve sırayı açar (Yetkili)")
@app_commands.describe(kategori="Hangi kategori için sıra paneli kurulacak?")
@app_commands.choices(kategori=KATEGORI_CHOICES)
@app_commands.default_permissions(administrator=True)
async def cmd_sirakur_alias(interaction: discord.Interaction, kategori: app_commands.Choice[str]):
    await cmd_sira_kur(interaction, kategori)


@bot.tree.command(name="sira-kapat", description="Sırayı kapatır ve sıraya katılma butonunu kanaldan tamamen kaldırır (Yetkili)")
@app_commands.describe(kategori="Kapatılacak sıra kategorisi")
@app_commands.choices(kategori=KATEGORI_CHOICES)
@app_commands.default_permissions(administrator=True)
async def cmd_sira_kapat(interaction: discord.Interaction, kategori: app_commands.Choice[str]):
    if not is_tester_or_admin(interaction.user):
        await interaction.response.send_message("❌ Bu komutu sadece yetkililer kullanabilir!", ephemeral=True)
        return

    kat_adi = kategori.value
    kat_data = db.get(kat_adi, {})
    kat_data["is_open"] = False
    save_data(db)

    # İlgili kanalı bul
    channel = interaction.channel
    ch_id = kat_data.get("channel_id")
    if ch_id:
        c = bot.get_channel(int(ch_id))
        if c:
            channel = c

    # Kanaldaki eski "Sıraya Katıl" / "Tier Test Sırası" mesajlarını bul ve TAMAMEN SİL!
    try:
        async for m in channel.history(limit=25):
            if m.author.id == bot.user.id:
                # Butonlu mesaj veya sıra embed'i ise direkt sil
                if len(m.components) > 0 or (m.embeds and any("Tier Test Sırası" in (e.title or "") for e in m.embeds)):
                    try:
                        await m.delete()
                    except Exception:
                        pass
    except Exception as e:
        print(f"Mesaj temizleme hatası: {e}")

    kat_data["message_id"] = None
    save_data(db)

    # Kanala herkesin göreceği kapalı duyurusu at
    closed_embed = discord.Embed(
        title=f"🔒 {kat_adi} - Sıra Kapatıldı",
        description=(
            f"🔴 **{kat_adi}** tier test başvuruları yetkililer tarafından **geçici olarak kapatılmıştır.**\n\n"
            "Yeni başvuru alınmamaktadır. Tekrar açıldığında buradan duyurulacaktır."
        ),
        color=0xED4245,
        timestamp=datetime.now()
    )
    closed_embed.set_footer(text=f"{SERVER_NAME} • Tier Sistemi")
    await channel.send(embed=closed_embed)

    await interaction.response.send_message(f"✅ **{kat_adi}** sırası kapatıldı ve sıraya katılma butonları kanaldan silindi!", ephemeral=True)


@bot.tree.command(name="sirakapat", description="Sırayı kapatır ve sıraya katılma butonunu kanaldan tamamen kaldırır (Yetkili)")
@app_commands.describe(kategori="Kapatılacak sıra kategorisi")
@app_commands.choices(kategori=KATEGORI_CHOICES)
@app_commands.default_permissions(administrator=True)
async def cmd_sirakapat_alias(interaction: discord.Interaction, kategori: app_commands.Choice[str]):
    await cmd_sira_kapat(interaction, kategori)


@bot.tree.command(name="sira-ac", description="Kapalı sırayı tekrar açar ve sıraya katıl butonunu kanala getirir (Yetkili)")
@app_commands.describe(kategori="Açılacak sıra kategorisi")
@app_commands.choices(kategori=KATEGORI_CHOICES)
@app_commands.default_permissions(administrator=True)
async def cmd_sira_ac(interaction: discord.Interaction, kategori: app_commands.Choice[str]):
    if not is_tester_or_admin(interaction.user):
        await interaction.response.send_message("❌ Bu komutu sadece yetkililer kullanabilir!", ephemeral=True)
        return

    kat_adi = kategori.value
    kat_data = db.get(kat_adi, {})
    kat_data["is_open"] = True
    kat_data["channel_id"] = interaction.channel_id
    if "list" not in kat_data:
        kat_data["list"] = []
    db[kat_adi] = kat_data
    save_data(db)

    # Kanaldaki eski kapalı duyurularını temizle
    try:
        async for m in interaction.channel.history(limit=15):
            if m.author.id == bot.user.id and m.embeds and any("Sıra Kapatıldı" in (e.title or "") for e in m.embeds):
                try:
                    await m.delete()
                except Exception:
                    pass
    except Exception:
        pass

    embed = build_queue_embed(kat_adi)
    view = QueueControlView(kat_adi)
    msg = await interaction.channel.send(embed=embed, view=view)
    kat_data["message_id"] = msg.id
    save_data(db)

    await interaction.response.send_message(f"🟢 **{kat_adi}** sırası tekrar açıldı ve butonlar kanala yerleştirildi!", ephemeral=True)


@bot.tree.command(name="siraac", description="Kapalı sırayı tekrar açar ve sıraya katıl butonunu kanala getirir (Yetkili)")
@app_commands.describe(kategori="Açılacak sıra kategorisi")
@app_commands.choices(kategori=KATEGORI_CHOICES)
@app_commands.default_permissions(administrator=True)
async def cmd_siraac_alias(interaction: discord.Interaction, kategori: app_commands.Choice[str]):
    await cmd_sira_ac(interaction, kategori)


@bot.tree.command(name="tier-ver", description="Oyuncuya tier ver ve sıradan çıkar (Yetkili)")
@app_commands.describe(
    oyuncu="Tier verilecek Discord kullanıcısı",
    tier="Verilecek Tier",
    skor="Skor (Örn: 2-0)",
    kategori="Kategori (isteğe bağlı, belirtilmezse sıradaki kategori alınır)"
)
@app_commands.choices(kategori=KATEGORI_CHOICES, tier=TIER_CHOICES)
@app_commands.default_permissions(administrator=True)
async def cmd_tier_ver(
    interaction: discord.Interaction,
    oyuncu: discord.Member,
    tier: app_commands.Choice[str],
    skor: str,
    kategori: app_commands.Choice[str] = None
):
    if not is_tester_or_admin(interaction.user):
        await interaction.response.send_message("❌ Bu komutu sadece Tester/Yetkililer kullanabilir!", ephemeral=True)
        return

    tier_val = tier.value
    target_kat = kategori.value if kategori else None
    if not target_kat:
        for kat_name, k_info in db.items():
            for item in k_info.get("list", []):
                if item["user_id"] == oyuncu.id:
                    target_kat = kat_name
                    break
            if target_kat:
                break

    if not target_kat:
        target_kat = "TrapPvP"

    await process_tier_give(
        interaction=interaction,
        target_user_id=oyuncu.id,
        kategori=target_kat,
        tier=tier_val,
        skor=skor,
        ticket_channel=interaction.channel
    )


@bot.tree.command(name="tierver", description="Oyuncuya tier ver ve sıradan çıkar (Yetkili)")
@app_commands.describe(
    oyuncu="Tier verilecek Discord kullanıcısı",
    tier="Verilecek Tier",
    skor="Skor (Örn: 2-0)",
    kategori="Kategori (isteğe bağlı, belirtilmezse sıradaki kategori alınır)"
)
@app_commands.choices(kategori=KATEGORI_CHOICES, tier=TIER_CHOICES)
@app_commands.default_permissions(administrator=True)
async def cmd_tierver_alias(
    interaction: discord.Interaction,
    oyuncu: discord.Member,
    tier: app_commands.Choice[str],
    skor: str,
    kategori: app_commands.Choice[str] = None
):
    await cmd_tier_ver(interaction, oyuncu, tier, skor, kategori)



@bot.tree.command(name="sira-sil", description="Bir oyuncuyu sıradan manuel çıkar (Yetkili)")
@app_commands.describe(oyuncu="Sıradan çıkarılacak oyuncu")
@app_commands.default_permissions(administrator=True)
async def cmd_sira_sil(interaction: discord.Interaction, oyuncu: discord.Member):
    if not is_tester_or_admin(interaction.user):
        await interaction.response.send_message("❌ Bu komutu sadece yetkililer kullanabilir!", ephemeral=True)
        return

    found = False
    for kat_name, k_info in db.items():
        q_list = k_info.get("list", [])
        initial_len = len(q_list)
        k_info["list"] = [x for x in q_list if x["user_id"] != oyuncu.id]
        if len(k_info["list"]) < initial_len:
            found = True
            save_data(db)
            await update_queue_message(kat_name)

    if found:
        await interaction.response.send_message(f"✅ {oyuncu.mention} sıradan silindi.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ {oyuncu.mention} hiçbir sırada bulunamadı.", ephemeral=True)


@bot.tree.command(name="sira-temizle", description="Bir kategorideki tüm sırayı temizler (Yetkili)")
@app_commands.describe(kategori="Sırası temizlenecek kategori")
@app_commands.choices(kategori=KATEGORI_CHOICES)
@app_commands.default_permissions(administrator=True)
async def cmd_sira_temizle(interaction: discord.Interaction, kategori: app_commands.Choice[str]):
    if not is_tester_or_admin(interaction.user):
        await interaction.response.send_message("❌ Bu komutu sadece yetkililer kullanabilir!", ephemeral=True)
        return

    kat_adi = kategori.value
    if kat_adi in db:
        db[kat_adi]["list"] = []
        save_data(db)
        await update_queue_message(kat_adi)
    else:
        await interaction.response.send_message("❌ Kategori bulunamadı!", ephemeral=True)


@bot.tree.command(name="test-kapat", description="Aktif bir testi veya ticket'ı iptal eder/kapatır (Tester/Yetkili)")
@app_commands.describe(oyuncu="Testi kapatılacak oyuncu (Ticket kanalında yazıyorsan boş bırakabilirsin)")
@app_commands.default_permissions(administrator=True)
async def cmd_test_kapat(interaction: discord.Interaction, oyuncu: discord.Member = None):
    if not is_tester_or_admin(interaction.user):
        await interaction.response.send_message("❌ Bu komutu sadece Tester/Yetkililer kullanabilir!", ephemeral=True)
        return

    target_id = oyuncu.id if oyuncu else None
    ticket_channel_to_delete = None

    # SADECE botun açtığı özel ticket kanalında çalışsın (Genel kanallar asla silinemez)
    if not target_id and isinstance(interaction.channel, discord.TextChannel) and interaction.channel.topic and "Tier Test Ticket" in interaction.channel.topic:
        ticket_channel_to_delete = interaction.channel
        for kat_name, k_info in db.items():
            for item in k_info.get("list", []):
                if item.get("ticket_id") == interaction.channel_id:
                    target_id = item["user_id"]
                    break
            if target_id:
                break

    if not target_id and not ticket_channel_to_delete:
        await interaction.response.send_message("❌ Lütfen oyuncu belirt veya bu komutu test ticket kanalında kullan!", ephemeral=True)
        return

    updated_kats = []
    for kat_name, k_info in db.items():
        q_list = k_info.get("list", [])
        initial_len = len(q_list)
        for item in q_list:
            if item["user_id"] == target_id:
                if not ticket_channel_to_delete and item.get("ticket_id"):
                    t_ch = interaction.guild.get_channel(int(item["ticket_id"]))
                    if t_ch:
                        ticket_channel_to_delete = t_ch
        k_info["list"] = [x for x in q_list if x["user_id"] != target_id]
        if len(k_info["list"]) < initial_len:
            updated_kats.append(kat_name)

    save_data(db)
    for k in updated_kats:
        await update_queue_message(k)

    await interaction.response.send_message("🔒 Test başarıyla sonlandırıldı ve oyuncu sıradan düşürüldü.", ephemeral=True)

    if ticket_channel_to_delete:
        await asyncio.sleep(2)
        try:
            await ticket_channel_to_delete.delete()
        except Exception:
            pass


@bot.tree.command(name="sira-sifirla", description="Tüm sıraları ve takılı kalan kayıtları tamamen temizler (Yetkili)")
@app_commands.default_permissions(administrator=True)
async def cmd_sira_sifirla(interaction: discord.Interaction):
    if not is_tester_or_admin(interaction.user):
        await interaction.response.send_message("❌ Bu komutu sadece yetkililer kullanabilir!", ephemeral=True)
        return
    for kat_info in db.values():
        kat_info["list"] = []
    save_data(db)
    for kat in db.keys():
        await update_queue_message(kat)
    await interaction.response.send_message("🧹 Tüm sıralar ve takılı kalan başvurular tamamen sıfırlandı!", ephemeral=True)





@bot.tree.error
async def on_tree_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandInvokeError) and isinstance(error.original, discord.Forbidden):
        msg = (
            "❌ **Yetki Hatası (403):** Botun bu kanala mesaj atma veya yönetme izni yok!\n"
            "👉 Kanal kilitli olduğu için bot mesaj gönderemiyor.\n"
            "👉 Lütfen Discord sunucu ayarlarından **TierListBot** rolüne **Yönetici (Administrator)** yetkisi verin veya botun bu kanalda **Mesaj Gönder** yetkisini açın!"
        )
    else:
        msg = f"❌ Bir hata oluştu: {error}"

    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════
#                    BOT ON READY
# ═══════════════════════════════════════════════════════════════
@bot.event
async def on_ready():
    print(f"✅ Bot hazır ve çevrimiçi: {bot.user} (ID: {bot.user.id})")

    # Tüm kategoriler için persistent butonları yeniden kaydet
    for kat in KATEGORILER:
        bot.add_view(QueueControlView(kat))

    try:
        bot.tree.copy_global_to(guild=GUILD_ID)
        synced = await bot.tree.sync(guild=GUILD_ID)
        print(f"🔄 {len(synced)} slash komutu sunucuya (guild) başarıyla senkronize edildi.", flush=True)
    except Exception as e:
        print(f"Guild sync hatası: {e}", flush=True)

    try:
        synced_global = await bot.tree.sync()
        print(f"🌍 {len(synced_global)} slash komutu global senkronize edildi.", flush=True)
    except Exception as e:
        print(f"Global sync hatası: {e}", flush=True)

    # Mevcut açık test ticket'larının menü ve butonlarını da yeniden kaydet
    for kat, kat_info in db.items():
        for item in kat_info.get("list", []):
            if item.get("status") == "testing" and item.get("ticket_id"):
                try:
                    bot.add_view(TicketControlView(kat, item["user_id"]))
                except Exception as e:
                    print(f"Ticket view yükleme hatası: {e}")

    # Mevcut sıra panellerini tekrar canlandır
    for kat in db.keys():
        try:
            await update_queue_message(kat)
        except Exception:
            pass



if __name__ == "__main__":
    bot.run(TOKEN)

