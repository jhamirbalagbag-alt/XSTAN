import discord
from discord.ext import commands, tasks
from discord import app_commands
import sqlite3
import asyncio
import os
import random
import time
import datetime
import json
import re
import io
import traceback
import math
import hashlib
import copy
from collections import defaultdict
from typing import Optional, Union
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN", "")
OWNER_IDS_RAW = os.getenv("BOT_OWNER_IDS", "")
OWNER_IDS = set(int(x.strip()) for x in OWNER_IDS_RAW.split(",") if x.strip().isdigit())
DB_PATH = os.getenv("DB_PATH", "bot.db")
CURRENCY_NAME = os.getenv("CURRENCY_NAME", "XS")
PREFIXES = ["X", "S"]

intents = discord.Intents.all()

def get_prefix(bot, message):
    return PREFIXES

bot = commands.Bot(command_prefix=get_prefix, intents=intents, help_command=None)

# ─── DATABASE ─────────────────────────────────────────────────────────────────

def db_connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def db_init():
    with db_connect() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS economy (
            user_id INTEGER,
            guild_id INTEGER,
            wallet INTEGER DEFAULT 0,
            bank INTEGER DEFAULT 0,
            total_earned INTEGER DEFAULT 0,
            total_spent INTEGER DEFAULT 0,
            last_daily INTEGER DEFAULT 0,
            last_weekly INTEGER DEFAULT 0,
            last_work INTEGER DEFAULT 0,
            last_beg INTEGER DEFAULT 0,
            last_crime INTEGER DEFAULT 0,
            last_slut INTEGER DEFAULT 0,
            last_search INTEGER DEFAULT 0,
            last_rob INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, guild_id)
        );
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            guild_id INTEGER,
            item_name TEXT,
            quantity INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS shop (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            item_name TEXT,
            description TEXT,
            price INTEGER,
            stock INTEGER DEFAULT -1,
            role_required INTEGER DEFAULT NULL
        );
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            user_id INTEGER,
            action TEXT,
            amount INTEGER,
            timestamp INTEGER
        );
        CREATE TABLE IF NOT EXISTS warnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            user_id INTEGER,
            moderator_id INTEGER,
            reason TEXT,
            timestamp INTEGER
        );
        CREATE TABLE IF NOT EXISTS mod_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            user_id INTEGER,
            moderator_id INTEGER,
            action TEXT,
            reason TEXT,
            timestamp INTEGER
        );
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            channel_id INTEGER,
            creator_id INTEGER,
            claimed_by INTEGER DEFAULT NULL,
            status TEXT DEFAULT 'open',
            close_reason TEXT DEFAULT NULL,
            created_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS ticket_config (
            guild_id INTEGER PRIMARY KEY,
            panel_channel INTEGER DEFAULT NULL,
            log_channel INTEGER DEFAULT NULL,
            support_role INTEGER DEFAULT NULL,
            category_id INTEGER DEFAULT NULL,
            max_tickets INTEGER DEFAULT 3
        );
        CREATE TABLE IF NOT EXISTS ticket_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER,
            author_id INTEGER,
            author_name TEXT,
            content TEXT,
            timestamp INTEGER
        );
        CREATE TABLE IF NOT EXISTS guild_config (
            guild_id INTEGER PRIMARY KEY,
            log_channel INTEGER DEFAULT NULL,
            welcome_channel INTEGER DEFAULT NULL,
            leave_channel INTEGER DEFAULT NULL,
            welcome_message TEXT DEFAULT NULL,
            leave_message TEXT DEFAULT NULL,
            mod_log_channel INTEGER DEFAULT NULL,
            suggest_channel INTEGER DEFAULT NULL,
            report_channel INTEGER DEFAULT NULL,
            antinuke_enabled INTEGER DEFAULT 0,
            antinuke_log_channel INTEGER DEFAULT NULL,
            antispam_enabled INTEGER DEFAULT 0,
            daily_amount INTEGER DEFAULT 500,
            weekly_amount INTEGER DEFAULT 2500,
            work_min INTEGER DEFAULT 100,
            work_max INTEGER DEFAULT 500,
            beg_chance INTEGER DEFAULT 60,
            crime_chance INTEGER DEFAULT 50,
            starting_balance INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS sticky_messages (
            guild_id INTEGER,
            channel_id INTEGER,
            content TEXT,
            last_message_id INTEGER DEFAULT NULL,
            PRIMARY KEY (guild_id, channel_id)
        );
        CREATE TABLE IF NOT EXISTS snipe_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            channel_id INTEGER,
            author_id INTEGER,
            author_name TEXT,
            content TEXT,
            deleted_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS edit_snipe (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            channel_id INTEGER,
            author_id INTEGER,
            author_name TEXT,
            before_content TEXT,
            after_content TEXT,
            edited_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            channel_id INTEGER,
            message TEXT,
            remind_at INTEGER,
            created_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS afk (
            user_id INTEGER,
            guild_id INTEGER,
            reason TEXT,
            set_at INTEGER,
            PRIMARY KEY (user_id, guild_id)
        );
        CREATE TABLE IF NOT EXISTS antinuke_config (
            guild_id INTEGER PRIMARY KEY,
            enabled INTEGER DEFAULT 0,
            channel_delete_limit INTEGER DEFAULT 3,
            channel_create_limit INTEGER DEFAULT 5,
            role_delete_limit INTEGER DEFAULT 3,
            role_create_limit INTEGER DEFAULT 5,
            ban_limit INTEGER DEFAULT 5,
            kick_limit INTEGER DEFAULT 5,
            webhook_limit INTEGER DEFAULT 3,
            time_window INTEGER DEFAULT 10,
            action TEXT DEFAULT 'kick',
            lockdown_duration INTEGER DEFAULT 600
        );
        CREATE TABLE IF NOT EXISTS antinuke_whitelist (
            guild_id INTEGER,
            entity_id INTEGER,
            PRIMARY KEY (guild_id, entity_id)
        );
        CREATE TABLE IF NOT EXISTS antinuke_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            event_type TEXT,
            actor_id INTEGER,
            target TEXT,
            action_taken TEXT,
            timestamp INTEGER
        );
        CREATE TABLE IF NOT EXISTS server_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            snapshot_data TEXT,
            created_at INTEGER,
            label TEXT DEFAULT NULL
        );
        CREATE TABLE IF NOT EXISTS blacklist (
            user_id INTEGER PRIMARY KEY
        );
        CREATE TABLE IF NOT EXISTS game_stats (
            user_id INTEGER,
            guild_id INTEGER,
            game TEXT,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, guild_id, game)
        );
        """)

db_init()

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def is_owner():
    async def predicate(ctx):
        return ctx.author.id in OWNER_IDS
    return commands.check(predicate)

def is_blacklisted():
    async def predicate(ctx):
        with db_connect() as conn:
            row = conn.execute("SELECT 1 FROM blacklist WHERE user_id=?", (ctx.author.id,)).fetchone()
        if row:
            await ctx.send("You are blacklisted from using this bot.")
            return False
        return True
    return commands.check(predicate)

def ensure_economy(user_id: int, guild_id: int):
    with db_connect() as conn:
        existing = conn.execute("SELECT 1 FROM economy WHERE user_id=? AND guild_id=?", (user_id, guild_id)).fetchone()
        if not existing:
            cfg = conn.execute("SELECT starting_balance FROM guild_config WHERE guild_id=?", (guild_id,)).fetchone()
            start = cfg["starting_balance"] if cfg else 0
            conn.execute("INSERT OR IGNORE INTO economy(user_id,guild_id,wallet) VALUES(?,?,?)", (user_id, guild_id, start))

def get_balance(user_id: int, guild_id: int):
    ensure_economy(user_id, guild_id)
    with db_connect() as conn:
        row = conn.execute("SELECT wallet, bank FROM economy WHERE user_id=? AND guild_id=?", (user_id, guild_id)).fetchone()
    return dict(row) if row else {"wallet": 0, "bank": 0}

def add_wallet(user_id: int, guild_id: int, amount: int):
    ensure_economy(user_id, guild_id)
    with db_connect() as conn:
        if amount > 0:
            conn.execute("UPDATE economy SET wallet=wallet+?, total_earned=total_earned+? WHERE user_id=? AND guild_id=?", (amount, amount, user_id, guild_id))
        else:
            conn.execute("UPDATE economy SET wallet=MAX(0,wallet+?) WHERE user_id=? AND guild_id=?", (amount, user_id, guild_id))

def add_bank(user_id: int, guild_id: int, amount: int):
    ensure_economy(user_id, guild_id)
    with db_connect() as conn:
        if amount > 0:
            conn.execute("UPDATE economy SET bank=bank+?, total_earned=total_earned+? WHERE user_id=? AND guild_id=?", (amount, amount, user_id, guild_id))
        else:
            conn.execute("UPDATE economy SET bank=MAX(0,bank+?) WHERE user_id=? AND guild_id=?", (amount, user_id, guild_id))

def log_transaction(guild_id, user_id, action, amount):
    with db_connect() as conn:
        conn.execute("INSERT INTO transactions(guild_id,user_id,action,amount,timestamp) VALUES(?,?,?,?,?)",
                     (guild_id, user_id, action, amount, int(time.time())))

def get_guild_cfg(guild_id):
    with db_connect() as conn:
        row = conn.execute("SELECT * FROM guild_config WHERE guild_id=?", (guild_id,)).fetchone()
    if not row:
        with db_connect() as conn:
            conn.execute("INSERT OR IGNORE INTO guild_config(guild_id) VALUES(?)", (guild_id,))
            row = conn.execute("SELECT * FROM guild_config WHERE guild_id=?", (guild_id,)).fetchone()
    return dict(row)

def set_guild_cfg(guild_id, **kwargs):
    get_guild_cfg(guild_id)
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [guild_id]
    with db_connect() as conn:
        conn.execute(f"UPDATE guild_config SET {sets} WHERE guild_id=?", vals)

def on_cooldown(last_time: int, seconds: int):
    now = int(time.time())
    diff = now - last_time
    if diff < seconds:
        return seconds - diff
    return 0

def fmt_time(seconds: int):
    h, r = divmod(seconds, 3600)
    m, s = divmod(r, 60)
    parts = []
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    if s: parts.append(f"{s}s")
    return " ".join(parts) if parts else "0s"

def base_embed(title="", description="", color=0x5865F2):
    return discord.Embed(title=title, description=description, color=color)

def add_mod_case(guild_id, user_id, mod_id, action, reason):
    with db_connect() as conn:
        conn.execute("INSERT INTO mod_cases(guild_id,user_id,moderator_id,action,reason,timestamp) VALUES(?,?,?,?,?,?)",
                     (guild_id, user_id, mod_id, action, reason, int(time.time())))
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

async def send_mod_log(guild, action, user, mod, reason, case_id=None):
    cfg = get_guild_cfg(guild.id)
    ch_id = cfg.get("mod_log_channel")
    if not ch_id:
        return
    ch = guild.get_channel(ch_id)
    if not ch:
        return
    e = base_embed(title=f"Moderation — {action}", color=0xED4245)
    e.add_field(name="User", value=f"{user} ({user.id})", inline=True)
    e.add_field(name="Moderator", value=f"{mod} ({mod.id})", inline=True)
    e.add_field(name="Reason", value=reason or "No reason", inline=False)
    if case_id:
        e.set_footer(text=f"Case #{case_id}")
    e.timestamp = datetime.datetime.utcnow()
    try:
        await ch.send(embed=e)
    except Exception:
        pass

async def send_log(guild, event, description, color=0x5865F2):
    cfg = get_guild_cfg(guild.id)
    ch_id = cfg.get("log_channel")
    if not ch_id:
        return
    ch = guild.get_channel(ch_id)
    if not ch:
        return
    e = base_embed(title=event, description=description, color=color)
    e.timestamp = datetime.datetime.utcnow()
    try:
        await ch.send(embed=e)
    except Exception:
        pass

# ─── ANTINUKE TRACKER ─────────────────────────────────────────────────────────

class NukeTracker:
    def __init__(self):
        self.events = defaultdict(lambda: defaultdict(list))

    def record(self, guild_id, actor_id, event_type):
        now = time.time()
        self.events[guild_id][f"{actor_id}:{event_type}"].append(now)

    def count(self, guild_id, actor_id, event_type, window):
        now = time.time()
        key = f"{actor_id}:{event_type}"
        self.events[guild_id][key] = [t for t in self.events[guild_id][key] if now - t < window]
        return len(self.events[guild_id][key])

nuke_tracker = NukeTracker()

def get_antinuke_cfg(guild_id):
    with db_connect() as conn:
        row = conn.execute("SELECT * FROM antinuke_config WHERE guild_id=?", (guild_id,)).fetchone()
    if not row:
        with db_connect() as conn:
            conn.execute("INSERT OR IGNORE INTO antinuke_config(guild_id) VALUES(?)", (guild_id,))
            row = conn.execute("SELECT * FROM antinuke_config WHERE guild_id=?", (guild_id,)).fetchone()
    return dict(row)

def is_whitelisted(guild_id, entity_id):
    if entity_id in OWNER_IDS:
        return True
    with db_connect() as conn:
        row = conn.execute("SELECT 1 FROM antinuke_whitelist WHERE guild_id=? AND entity_id=?", (guild_id, entity_id)).fetchone()
    return bool(row)

def log_antinuke(guild_id, event_type, actor_id, target, action_taken):
    with db_connect() as conn:
        conn.execute("INSERT INTO antinuke_logs(guild_id,event_type,actor_id,target,action_taken,timestamp) VALUES(?,?,?,?,?,?)",
                     (guild_id, event_type, actor_id, str(target), action_taken, int(time.time())))

async def handle_nuke_action(guild, actor_id, event_type, action_taken_desc):
    cfg = get_antinuke_cfg(guild.id)
    log_antinuke(guild.id, event_type, actor_id, event_type, action_taken_desc)
    gcfg = get_guild_cfg(guild.id)
    log_ch_id = gcfg.get("antinuke_log_channel") or cfg.get("lockdown_duration")
    log_ch_id = gcfg.get("antinuke_log_channel")
    if log_ch_id:
        ch = guild.get_channel(log_ch_id)
        if ch:
            e = base_embed(title="Security Alert", color=0xFF0000)
            e.add_field(name="Event", value=event_type, inline=True)
            e.add_field(name="Actor", value=f"<@{actor_id}> ({actor_id})", inline=True)
            e.add_field(name="Action", value=action_taken_desc, inline=False)
            e.timestamp = datetime.datetime.utcnow()
            try:
                await ch.send(embed=e)
            except Exception:
                pass
    action = cfg.get("action", "kick")
    member = guild.get_member(actor_id)
    if not member:
        return
    if member.top_role >= guild.me.top_role:
        return
    if member.id == guild.owner_id:
        return
    try:
        if action == "kick":
            await guild.kick(member, reason=f"Anti-Nuke: {event_type}")
        elif action == "ban":
            await guild.ban(member, reason=f"Anti-Nuke: {event_type}", delete_message_days=0)
        elif action == "strip":
            await member.edit(roles=[], reason=f"Anti-Nuke: {event_type}")
    except Exception:
        pass

# ─── ANTISPAM TRACKER ─────────────────────────────────────────────────────────

class SpamTracker:
    def __init__(self):
        self.msgs = defaultdict(list)

    def record(self, guild_id, user_id):
        key = f"{guild_id}:{user_id}"
        now = time.time()
        self.msgs[key].append(now)
        self.msgs[key] = [t for t in self.msgs[key] if now - t < 5]
        return len(self.msgs[key])

spam_tracker = SpamTracker()

# ─── SNAPSHOT HELPERS ─────────────────────────────────────────────────────────

async def take_snapshot(guild):
    data = {"channels": [], "roles": [], "timestamp": int(time.time())}
    for ch in guild.channels:
        overwrites = {}
        for target, perms in ch.overwrites.items():
            overwrites[str(target.id)] = {"type": "role" if isinstance(target, discord.Role) else "member",
                                           "allow": perms.pair()[0].value, "deny": perms.pair()[1].value}
        entry = {"id": ch.id, "name": ch.name, "type": str(ch.type),
                 "position": ch.position, "category_id": ch.category_id if hasattr(ch, "category_id") else None,
                 "overwrites": overwrites}
        if hasattr(ch, "topic"):
            entry["topic"] = ch.topic
        if hasattr(ch, "slowmode_delay"):
            entry["slowmode_delay"] = ch.slowmode_delay
        if hasattr(ch, "nsfw"):
            entry["nsfw"] = ch.nsfw
        data["channels"].append(entry)
    for r in guild.roles:
        if r.is_default():
            continue
        data["roles"].append({"id": r.id, "name": r.name, "color": r.color.value,
                               "hoist": r.hoist, "mentionable": r.mentionable,
                               "permissions": r.permissions.value, "position": r.position})
    with db_connect() as conn:
        conn.execute("INSERT INTO server_snapshots(guild_id,snapshot_data,created_at) VALUES(?,?,?)",
                     (guild.id, json.dumps(data), int(time.time())))
    return data

# ─── BOT EVENTS ───────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"Online as {bot.user} ({bot.user.id})")
    reminder_task.start()
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="Xhelp | Shelp"))

@bot.event
async def on_member_join(member):
    cfg = get_guild_cfg(member.guild.id)
    ch_id = cfg.get("welcome_channel")
    if ch_id:
        ch = member.guild.get_channel(ch_id)
        if ch:
            msg = cfg.get("welcome_message") or f"Welcome {member.mention} to {member.guild.name}."
            msg = msg.replace("{user}", member.mention).replace("{server}", member.guild.name).replace("{count}", str(member.guild.member_count))
            try:
                await ch.send(msg)
            except Exception:
                pass
    await send_log(member.guild, "Member Joined", f"{member} ({member.id}) joined.", color=0x57F287)

@bot.event
async def on_member_remove(member):
    cfg = get_guild_cfg(member.guild.id)
    ch_id = cfg.get("leave_channel")
    if ch_id:
        ch = member.guild.get_channel(ch_id)
        if ch:
            msg = cfg.get("leave_message") or f"{member} has left {member.guild.name}."
            msg = msg.replace("{user}", str(member)).replace("{server}", member.guild.name)
            try:
                await ch.send(msg)
            except Exception:
                pass
    await send_log(member.guild, "Member Left", f"{member} ({member.id}) left.", color=0xED4245)

@bot.event
async def on_message_delete(message):
    if message.author.bot or not message.guild:
        return
    with db_connect() as conn:
        conn.execute("INSERT INTO snipe_messages(guild_id,channel_id,author_id,author_name,content,deleted_at) VALUES(?,?,?,?,?,?)",
                     (message.guild.id, message.channel.id, message.author.id, str(message.author), message.content or "", int(time.time())))
        conn.execute("DELETE FROM snipe_messages WHERE channel_id=? AND id NOT IN (SELECT id FROM snipe_messages WHERE channel_id=? ORDER BY deleted_at DESC LIMIT 10)",
                     (message.channel.id, message.channel.id))
    await send_log(message.guild, "Message Deleted", f"By {message.author} in {message.channel.mention}:\n{message.content[:500] or '(no text)'}", color=0xFEE75C)

@bot.event
async def on_message_edit(before, after):
    if before.author.bot or not before.guild:
        return
    if before.content == after.content:
        return
    with db_connect() as conn:
        conn.execute("INSERT INTO edit_snipe(guild_id,channel_id,author_id,author_name,before_content,after_content,edited_at) VALUES(?,?,?,?,?,?,?)",
                     (before.guild.id, before.channel.id, before.author.id, str(before.author), before.content or "", after.content or "", int(time.time())))
        conn.execute("DELETE FROM edit_snipe WHERE channel_id=? AND id NOT IN (SELECT id FROM edit_snipe WHERE channel_id=? ORDER BY edited_at DESC LIMIT 10)",
                     (before.channel.id, before.channel.id))
    await send_log(before.guild, "Message Edited", f"By {before.author} in {before.channel.mention}:\nBefore: {before.content[:250]}\nAfter: {after.content[:250]}", color=0xFEE75C)

@bot.event
async def on_message(message):
    if not message.guild or message.author.bot:
        await bot.process_commands(message)
        return
    with db_connect() as conn:
        bl = conn.execute("SELECT 1 FROM blacklist WHERE user_id=?", (message.author.id,)).fetchone()
    if bl:
        return
    cfg = get_guild_cfg(message.guild.id)
    if cfg.get("antispam_enabled"):
        count = spam_tracker.record(message.guild.id, message.author.id)
        if count >= 6:
            try:
                await message.delete()
                await message.channel.send(f"{message.author.mention} Slow down.", delete_after=5)
            except Exception:
                pass
            return
    # sticky
    with db_connect() as conn:
        sticky = conn.execute("SELECT * FROM sticky_messages WHERE guild_id=? AND channel_id=?",
                              (message.guild.id, message.channel.id)).fetchone()
    if sticky and not message.author.bot:
        asyncio.create_task(handle_sticky(message.channel, sticky))
    # afk check
    with db_connect() as conn:
        afk_row = conn.execute("SELECT * FROM afk WHERE user_id=? AND guild_id=?", (message.author.id, message.guild.id)).fetchone()
    if afk_row:
        with db_connect() as conn:
            conn.execute("DELETE FROM afk WHERE user_id=? AND guild_id=?", (message.author.id, message.guild.id))
        try:
            await message.channel.send(f"{message.author.mention} Welcome back. AFK removed.", delete_after=5)
        except Exception:
            pass
    for mention in message.mentions:
        with db_connect() as conn:
            afk_m = conn.execute("SELECT * FROM afk WHERE user_id=? AND guild_id=?", (mention.id, message.guild.id)).fetchone()
        if afk_m:
            try:
                await message.channel.send(f"{mention.display_name} is AFK: {afk_m['reason']}", delete_after=8)
            except Exception:
                pass
    await bot.process_commands(message)

async def handle_sticky(channel, sticky):
    await asyncio.sleep(1)
    try:
        if sticky["last_message_id"]:
            try:
                old = await channel.fetch_message(sticky["last_message_id"])
                await old.delete()
            except Exception:
                pass
        new_msg = await channel.send(sticky["content"])
        with db_connect() as conn:
            conn.execute("UPDATE sticky_messages SET last_message_id=? WHERE guild_id=? AND channel_id=?",
                         (new_msg.id, channel.guild.id, channel.id))
    except Exception:
        pass

@bot.event
async def on_guild_channel_delete(channel):
    guild = channel.guild
    cfg = get_antinuke_cfg(guild.id)
    if not cfg.get("enabled"):
        return
    await asyncio.sleep(1.5)
    try:
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.channel_delete):
            if abs((entry.created_at.replace(tzinfo=None) - datetime.datetime.utcnow()).total_seconds()) < 5:
                actor_id = entry.user.id
                if is_whitelisted(guild.id, actor_id):
                    return
                count = nuke_tracker.count(guild.id, actor_id, "channel_delete", cfg["time_window"])
                nuke_tracker.record(guild.id, actor_id, "channel_delete")
                if count + 1 >= cfg["channel_delete_limit"]:
                    await handle_nuke_action(guild, actor_id, "channel_delete", f"Deleted {count+1} channels in {cfg['time_window']}s")
                return
    except Exception:
        pass

@bot.event
async def on_guild_channel_create(channel):
    guild = channel.guild
    cfg = get_antinuke_cfg(guild.id)
    if not cfg.get("enabled"):
        return
    await asyncio.sleep(1.5)
    try:
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.channel_create):
            if abs((entry.created_at.replace(tzinfo=None) - datetime.datetime.utcnow()).total_seconds()) < 5:
                actor_id = entry.user.id
                if is_whitelisted(guild.id, actor_id):
                    return
                count = nuke_tracker.count(guild.id, actor_id, "channel_create", cfg["time_window"])
                nuke_tracker.record(guild.id, actor_id, "channel_create")
                if count + 1 >= cfg["channel_create_limit"]:
                    await handle_nuke_action(guild, actor_id, "channel_create", f"Created {count+1} channels in {cfg['time_window']}s")
                return
    except Exception:
        pass

@bot.event
async def on_guild_role_delete(role):
    guild = role.guild
    cfg = get_antinuke_cfg(guild.id)
    if not cfg.get("enabled"):
        return
    await asyncio.sleep(1.5)
    try:
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.role_delete):
            if abs((entry.created_at.replace(tzinfo=None) - datetime.datetime.utcnow()).total_seconds()) < 5:
                actor_id = entry.user.id
                if is_whitelisted(guild.id, actor_id):
                    return
                count = nuke_tracker.count(guild.id, actor_id, "role_delete", cfg["time_window"])
                nuke_tracker.record(guild.id, actor_id, "role_delete")
                if count + 1 >= cfg["role_delete_limit"]:
                    await handle_nuke_action(guild, actor_id, "role_delete", f"Deleted {count+1} roles in {cfg['time_window']}s")
                return
    except Exception:
        pass

@bot.event
async def on_guild_role_create(role):
    guild = role.guild
    cfg = get_antinuke_cfg(guild.id)
    if not cfg.get("enabled"):
        return
    await asyncio.sleep(1.5)
    try:
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.role_create):
            if abs((entry.created_at.replace(tzinfo=None) - datetime.datetime.utcnow()).total_seconds()) < 5:
                actor_id = entry.user.id
                if is_whitelisted(guild.id, actor_id):
                    return
                count = nuke_tracker.count(guild.id, actor_id, "role_create", cfg["time_window"])
                nuke_tracker.record(guild.id, actor_id, "role_create")
                if count + 1 >= cfg["role_create_limit"]:
                    await handle_nuke_action(guild, actor_id, "role_create", f"Created {count+1} roles in {cfg['time_window']}s")
                return
    except Exception:
        pass

@bot.event
async def on_member_ban(guild, user):
    cfg = get_antinuke_cfg(guild.id)
    if not cfg.get("enabled"):
        return
    await asyncio.sleep(1.5)
    try:
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
            if abs((entry.created_at.replace(tzinfo=None) - datetime.datetime.utcnow()).total_seconds()) < 5:
                actor_id = entry.user.id
                if is_whitelisted(guild.id, actor_id):
                    return
                count = nuke_tracker.count(guild.id, actor_id, "ban", cfg["time_window"])
                nuke_tracker.record(guild.id, actor_id, "ban")
                if count + 1 >= cfg["ban_limit"]:
                    await handle_nuke_action(guild, actor_id, "ban", f"Banned {count+1} members in {cfg['time_window']}s")
                return
    except Exception:
        pass

# ─── REMINDER TASK ────────────────────────────────────────────────────────────

@tasks.loop(seconds=30)
async def reminder_task():
    now = int(time.time())
    with db_connect() as conn:
        rows = conn.execute("SELECT * FROM reminders WHERE remind_at<=?", (now,)).fetchall()
        for row in rows:
            conn.execute("DELETE FROM reminders WHERE id=?", (row["id"],))
            ch = bot.get_channel(row["channel_id"])
            if ch:
                try:
                    await ch.send(f"<@{row['user_id']}> Reminder: {row['message']}")
                except Exception:
                    pass

# ─── HELP COMMAND ─────────────────────────────────────────────────────────────

HELP_PAGES = {
    "economy": {
        "title": "Economy",
        "commands": [
            ("balance [user]", "Check wallet and bank balance"),
            ("daily", "Collect daily reward"),
            ("weekly", "Collect weekly reward"),
            ("work", "Work for money"),
            ("beg", "Beg for coins"),
            ("crime", "Commit a crime (risky)"),
            ("slut", "Sell yourself (risky)"),
            ("search", "Search for coins"),
            ("deposit <amount|all>", "Deposit to bank"),
            ("withdraw <amount|all>", "Withdraw from bank"),
            ("pay <user> <amount>", "Pay another user"),
            ("leaderboard", "Top balances"),
            ("inventory [user]", "View inventory"),
            ("shop", "Browse the shop"),
            ("buy <item>", "Buy an item"),
            ("sell <item>", "Sell an item"),
            ("use <item>", "Use an item"),
            ("profile [user]", "View profile"),
            ("rob <user>", "Attempt to rob a user"),
            ("giveaway <amount>", "Giveaway coins in chat"),
        ]
    },
    "games": {
        "title": "Games",
        "commands": [
            ("coinflip <h|t> <bet>", "Flip a coin"),
            ("slots <bet>", "Spin the slots"),
            ("blackjack <bet>", "Play blackjack"),
            ("dice <bet>", "Roll dice (roll higher than bot)"),
            ("rps <rock|paper|scissors> <bet>", "Rock paper scissors"),
        ]
    },
    "tickets": {
        "title": "Tickets",
        "commands": [
            ("ticket setup", "Setup ticket system"),
            ("ticket panel", "Post the ticket panel"),
            ("ticket add <user>", "Add user to ticket"),
            ("ticket remove <user>", "Remove user from ticket"),
            ("ticket claim", "Claim a ticket"),
            ("ticket unclaim", "Unclaim a ticket"),
            ("ticket close [reason]", "Close a ticket"),
            ("ticket reopen", "Reopen a ticket"),
            ("ticket transcript", "Generate transcript"),
            ("ticket logs", "View ticket logs"),
            ("ticket config", "View ticket config"),
        ]
    },
    "moderation": {
        "title": "Moderation",
        "commands": [
            ("ban <user> [reason]", "Ban a user"),
            ("unban <user_id> [reason]", "Unban a user"),
            ("kick <user> [reason]", "Kick a user"),
            ("timeout <user> <duration> [reason]", "Timeout a user"),
            ("untimeout <user>", "Remove timeout"),
            ("warn <user> [reason]", "Warn a user"),
            ("warnings <user>", "View warnings"),
            ("clearwarns <user>", "Clear warnings"),
            ("purge <amount>", "Bulk delete messages"),
            ("slowmode <seconds>", "Set slowmode"),
            ("lock [channel]", "Lock a channel"),
            ("unlock [channel]", "Unlock a channel"),
            ("hide [channel]", "Hide a channel"),
            ("unhide [channel]", "Unhide a channel"),
            ("nick <user> [name]", "Change nickname"),
            ("role <user> <role>", "Give/remove role"),
            ("modlog [count]", "View mod logs"),
            ("case <id>", "View a mod case"),
        ]
    },
    "utility": {
        "title": "Utility",
        "commands": [
            ("ping", "Bot latency"),
            ("uptime", "Bot uptime"),
            ("server", "Server info"),
            ("userinfo [user]", "User info"),
            ("avatar [user]", "User avatar"),
            ("roleinfo <role>", "Role info"),
            ("channelinfo [channel]", "Channel info"),
            ("membercount", "Member count"),
            ("poll <question>", "Create a poll"),
            ("say <message>", "Bot says something"),
            ("remind <time> <message>", "Set a reminder"),
            ("afk [reason]", "Set AFK status"),
            ("report <user> [reason]", "Report a user"),
            ("suggest <text>", "Submit a suggestion"),
            ("firstmsg", "First message in channel"),
            ("servericon", "Server icon"),
            ("serverbanner", "Server banner"),
            ("snipe", "Last deleted message"),
            ("editsnipe", "Last edited message"),
        ]
    },
    "security": {
        "title": "Security",
        "commands": [
            ("antinuke setup", "Setup anti-nuke"),
            ("antinuke enable/disable", "Toggle anti-nuke"),
            ("antinuke status", "View status"),
            ("antinuke config <key> <value>", "Configure thresholds"),
            ("antinuke whitelist <user/id>", "Whitelist an entity"),
            ("antinuke unwhitelist <id>", "Remove from whitelist"),
            ("antinuke whitelist list", "View whitelist"),
            ("antinuke logs", "View security logs"),
            ("antinuke lockdown", "Manual lockdown"),
            ("antinuke unlock", "Release lockdown"),
            ("antinuke backup", "Take snapshot"),
            ("antinuke restore <id>", "Restore snapshot"),
            ("antinuke test", "Test anti-nuke alert"),
        ]
    },
    "owner": {
        "title": "Owner",
        "commands": [
            ("owner status", "Bot status"),
            ("owner servers", "List servers"),
            ("owner leave <guild_id>", "Leave a server"),
            ("owner shutdown", "Shutdown bot"),
            ("owner blacklist <user_id>", "Blacklist a user"),
            ("owner unblacklist <user_id>", "Remove from blacklist"),
            ("owner addcurrency <user> <amount>", "Add currency"),
            ("owner removecurrency <user> <amount>", "Remove currency"),
            ("owner resetbalance <user>", "Reset a user's balance"),
            ("owner maintenance", "Toggle maintenance mode"),
            ("owner setprefix <prefix>", "Change prefix (runtime)"),
        ]
    }
}

class HelpView(discord.ui.View):
    def __init__(self, pages, current="economy", ctx=None):
        super().__init__(timeout=120)
        self.pages = pages
        self.current = current
        self.ctx = ctx
        options = [discord.SelectOption(label=v["title"], value=k) for k, v in pages.items()]
        select = discord.ui.Select(placeholder="Select category", options=options)
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        if self.ctx and interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("Not your menu.", ephemeral=True)
            return
        self.current = interaction.data["values"][0]
        await interaction.response.edit_message(embed=self.build_embed())

    def build_embed(self):
        page = self.pages[self.current]
        e = base_embed(title=page["title"])
        desc = "\n".join(f"`{c}` — {d}" for c, d in page["commands"])
        e.description = desc
        e.set_footer(text="Use X or S as prefix")
        return e

@bot.command(name="help")
@commands.check(lambda ctx: not db_connect().execute("SELECT 1 FROM blacklist WHERE user_id=?", (ctx.author.id,)).fetchone())
async def help_cmd(ctx, category: str = None):
    pages = {k: v for k, v in HELP_PAGES.items()}
    if ctx.author.id not in OWNER_IDS:
        pages.pop("owner", None)
    if category:
        category = category.lower()
        if category == "all":
            e = base_embed(title="All Commands")
            for k, v in pages.items():
                cmds = ", ".join(f"`{c}`" for c, _ in v["commands"])
                e.add_field(name=v["title"], value=cmds, inline=False)
            return await ctx.send(embed=e)
        if category in pages:
            view = HelpView(pages, current=category, ctx=ctx)
            return await ctx.send(embed=view.build_embed(), view=view)
        return await ctx.send("Unknown category.")
    view = HelpView(pages, current="economy", ctx=ctx)
    await ctx.send(embed=view.build_embed(), view=view)

# ─── ECONOMY ──────────────────────────────────────────────────────────────────

@bot.command(name="balance", aliases=["bal"])
async def balance(ctx, user: discord.Member = None):
    user = user or ctx.author
    b = get_balance(user.id, ctx.guild.id)
    e = base_embed(title=f"{user.display_name} — Balance")
    e.add_field(name="Wallet", value=f"{b['wallet']:,} {CURRENCY_NAME}", inline=True)
    e.add_field(name="Bank", value=f"{b['bank']:,} {CURRENCY_NAME}", inline=True)
    e.add_field(name="Total", value=f"{b['wallet']+b['bank']:,} {CURRENCY_NAME}", inline=True)
    await ctx.send(embed=e)

@bot.command(name="daily")
async def daily(ctx):
    ensure_economy(ctx.author.id, ctx.guild.id)
    cfg = get_guild_cfg(ctx.guild.id)
    with db_connect() as conn:
        row = conn.execute("SELECT last_daily FROM economy WHERE user_id=? AND guild_id=?", (ctx.author.id, ctx.guild.id)).fetchone()
    cd = on_cooldown(row["last_daily"] if row else 0, 86400)
    if cd:
        return await ctx.send(f"Daily available in {fmt_time(cd)}.")
    amount = cfg.get("daily_amount", 500)
    add_wallet(ctx.author.id, ctx.guild.id, amount)
    with db_connect() as conn:
        conn.execute("UPDATE economy SET last_daily=? WHERE user_id=? AND guild_id=?", (int(time.time()), ctx.author.id, ctx.guild.id))
    log_transaction(ctx.guild.id, ctx.author.id, "daily", amount)
    await ctx.send(embed=base_embed(description=f"You collected **{amount:,} {CURRENCY_NAME}**.", color=0x57F287))

@bot.command(name="weekly")
async def weekly(ctx):
    ensure_economy(ctx.author.id, ctx.guild.id)
    cfg = get_guild_cfg(ctx.guild.id)
    with db_connect() as conn:
        row = conn.execute("SELECT last_weekly FROM economy WHERE user_id=? AND guild_id=?", (ctx.author.id, ctx.guild.id)).fetchone()
    cd = on_cooldown(row["last_weekly"] if row else 0, 604800)
    if cd:
        return await ctx.send(f"Weekly available in {fmt_time(cd)}.")
    amount = cfg.get("weekly_amount", 2500)
    add_wallet(ctx.author.id, ctx.guild.id, amount)
    with db_connect() as conn:
        conn.execute("UPDATE economy SET last_weekly=? WHERE user_id=? AND guild_id=?", (int(time.time()), ctx.author.id, ctx.guild.id))
    log_transaction(ctx.guild.id, ctx.author.id, "weekly", amount)
    await ctx.send(embed=base_embed(description=f"You collected **{amount:,} {CURRENCY_NAME}**.", color=0x57F287))

@bot.command(name="work")
async def work(ctx):
    ensure_economy(ctx.author.id, ctx.guild.id)
    cfg = get_guild_cfg(ctx.guild.id)
    with db_connect() as conn:
        row = conn.execute("SELECT last_work FROM economy WHERE user_id=? AND guild_id=?", (ctx.author.id, ctx.guild.id)).fetchone()
    cd = on_cooldown(row["last_work"] if row else 0, 3600)
    if cd:
        return await ctx.send(f"Work available in {fmt_time(cd)}.")
    amount = random.randint(cfg.get("work_min", 100), cfg.get("work_max", 500))
    jobs = ["developer", "driver", "chef", "cleaner", "teacher", "mechanic"]
    job = random.choice(jobs)
    add_wallet(ctx.author.id, ctx.guild.id, amount)
    with db_connect() as conn:
        conn.execute("UPDATE economy SET last_work=? WHERE user_id=? AND guild_id=?", (int(time.time()), ctx.author.id, ctx.guild.id))
    log_transaction(ctx.guild.id, ctx.author.id, "work", amount)
    await ctx.send(embed=base_embed(description=f"You worked as a **{job}** and earned **{amount:,} {CURRENCY_NAME}**."))

@bot.command(name="beg")
async def beg(ctx):
    ensure_economy(ctx.author.id, ctx.guild.id)
    cfg = get_guild_cfg(ctx.guild.id)
    with db_connect() as conn:
        row = conn.execute("SELECT last_beg FROM economy WHERE user_id=? AND guild_id=?", (ctx.author.id, ctx.guild.id)).fetchone()
    cd = on_cooldown(row["last_beg"] if row else 0, 60)
    if cd:
        return await ctx.send(f"Beg available in {fmt_time(cd)}.")
    chance = cfg.get("beg_chance", 60)
    if random.randint(1, 100) <= chance:
        amount = random.randint(10, 200)
        add_wallet(ctx.author.id, ctx.guild.id, amount)
        msg = f"Someone took pity on you. You received **{amount:,} {CURRENCY_NAME}**."
    else:
        msg = "Nobody gave you anything."
    with db_connect() as conn:
        conn.execute("UPDATE economy SET last_beg=? WHERE user_id=? AND guild_id=?", (int(time.time()), ctx.author.id, ctx.guild.id))
    await ctx.send(embed=base_embed(description=msg))

@bot.command(name="crime")
async def crime(ctx):
    ensure_economy(ctx.author.id, ctx.guild.id)
    cfg = get_guild_cfg(ctx.guild.id)
    with db_connect() as conn:
        row = conn.execute("SELECT last_crime FROM economy WHERE user_id=? AND guild_id=?", (ctx.author.id, ctx.guild.id)).fetchone()
    cd = on_cooldown(row["last_crime"] if row else 0, 3600)
    if cd:
        return await ctx.send(f"Crime available in {fmt_time(cd)}.")
    chance = cfg.get("crime_chance", 50)
    with db_connect() as conn:
        conn.execute("UPDATE economy SET last_crime=? WHERE user_id=? AND guild_id=?", (int(time.time()), ctx.author.id, ctx.guild.id))
    if random.randint(1, 100) <= chance:
        amount = random.randint(200, 800)
        add_wallet(ctx.author.id, ctx.guild.id, amount)
        msg = f"You got away with it. Earned **{amount:,} {CURRENCY_NAME}**."
    else:
        fine = random.randint(100, 400)
        b = get_balance(ctx.author.id, ctx.guild.id)
        fine = min(fine, b["wallet"])
        add_wallet(ctx.author.id, ctx.guild.id, -fine)
        msg = f"You got caught. Fined **{fine:,} {CURRENCY_NAME}**."
    await ctx.send(embed=base_embed(description=msg))

@bot.command(name="slut")
async def slut(ctx):
    ensure_economy(ctx.author.id, ctx.guild.id)
    with db_connect() as conn:
        row = conn.execute("SELECT last_slut FROM economy WHERE user_id=? AND guild_id=?", (ctx.author.id, ctx.guild.id)).fetchone()
    cd = on_cooldown(row["last_slut"] if row else 0, 1800)
    if cd:
        return await ctx.send(f"Available in {fmt_time(cd)}.")
    with db_connect() as conn:
        conn.execute("UPDATE economy SET last_slut=? WHERE user_id=? AND guild_id=?", (int(time.time()), ctx.author.id, ctx.guild.id))
    if random.randint(1, 100) <= 70:
        amount = random.randint(150, 600)
        add_wallet(ctx.author.id, ctx.guild.id, amount)
        msg = f"Earned **{amount:,} {CURRENCY_NAME}**."
    else:
        fine = random.randint(50, 200)
        b = get_balance(ctx.author.id, ctx.guild.id)
        fine = min(fine, b["wallet"])
        add_wallet(ctx.author.id, ctx.guild.id, -fine)
        msg = f"Things went wrong. Lost **{fine:,} {CURRENCY_NAME}**."
    await ctx.send(embed=base_embed(description=msg))

@bot.command(name="search")
async def search(ctx):
    ensure_economy(ctx.author.id, ctx.guild.id)
    with db_connect() as conn:
        row = conn.execute("SELECT last_search FROM economy WHERE user_id=? AND guild_id=?", (ctx.author.id, ctx.guild.id)).fetchone()
    cd = on_cooldown(row["last_search"] if row else 0, 600)
    if cd:
        return await ctx.send(f"Search available in {fmt_time(cd)}.")
    places = ["under the couch", "in a trash can", "behind a vending machine", "in an old jacket", "on the sidewalk"]
    place = random.choice(places)
    with db_connect() as conn:
        conn.execute("UPDATE economy SET last_search=? WHERE user_id=? AND guild_id=?", (int(time.time()), ctx.author.id, ctx.guild.id))
    if random.randint(1, 100) <= 75:
        amount = random.randint(20, 300)
        add_wallet(ctx.author.id, ctx.guild.id, amount)
        msg = f"You searched {place} and found **{amount:,} {CURRENCY_NAME}**."
    else:
        msg = f"You searched {place} and found nothing."
    await ctx.send(embed=base_embed(description=msg))

@bot.command(name="deposit", aliases=["dep"])
async def deposit(ctx, amount: str):
    b = get_balance(ctx.author.id, ctx.guild.id)
    if amount.lower() == "all":
        amt = b["wallet"]
    else:
        try:
            amt = int(amount)
        except ValueError:
            return await ctx.send("Invalid amount.")
    if amt <= 0:
        return await ctx.send("Invalid amount.")
    if b["wallet"] < amt:
        return await ctx.send("Not enough balance.")
    with db_connect() as conn:
        conn.execute("UPDATE economy SET wallet=wallet-?, bank=bank+? WHERE user_id=? AND guild_id=?", (amt, amt, ctx.author.id, ctx.guild.id))
    await ctx.send(embed=base_embed(description=f"Deposited **{amt:,} {CURRENCY_NAME}** to your bank."))

@bot.command(name="withdraw", aliases=["with"])
async def withdraw(ctx, amount: str):
    b = get_balance(ctx.author.id, ctx.guild.id)
    if amount.lower() == "all":
        amt = b["bank"]
    else:
        try:
            amt = int(amount)
        except ValueError:
            return await ctx.send("Invalid amount.")
    if amt <= 0:
        return await ctx.send("Invalid amount.")
    if b["bank"] < amt:
        return await ctx.send("Not enough in bank.")
    with db_connect() as conn:
        conn.execute("UPDATE economy SET bank=bank-?, wallet=wallet+? WHERE user_id=? AND guild_id=?", (amt, amt, ctx.author.id, ctx.guild.id))
    await ctx.send(embed=base_embed(description=f"Withdrew **{amt:,} {CURRENCY_NAME}** from your bank."))

@bot.command(name="pay")
async def pay(ctx, user: discord.Member, amount: int):
    if user.id == ctx.author.id:
        return await ctx.send("You cannot pay yourself.")
    if amount <= 0:
        return await ctx.send("Invalid amount.")
    b = get_balance(ctx.author.id, ctx.guild.id)
    if b["wallet"] < amount:
        return await ctx.send("Not enough balance.")
    with db_connect() as conn:
        conn.execute("UPDATE economy SET wallet=wallet-? WHERE user_id=? AND guild_id=?", (amount, ctx.author.id, ctx.guild.id))
        ensure_economy(user.id, ctx.guild.id)
        conn.execute("UPDATE economy SET wallet=wallet+?, total_earned=total_earned+? WHERE user_id=? AND guild_id=?", (amount, amount, user.id, ctx.guild.id))
    log_transaction(ctx.guild.id, ctx.author.id, f"pay->{user.id}", amount)
    await ctx.send(embed=base_embed(description=f"Paid **{amount:,} {CURRENCY_NAME}** to {user.mention}."))

@bot.command(name="leaderboard", aliases=["lb"])
async def leaderboard(ctx):
    with db_connect() as conn:
        rows = conn.execute("SELECT user_id, wallet+bank as total FROM economy WHERE guild_id=? ORDER BY total DESC LIMIT 10", (ctx.guild.id,)).fetchall()
    e = base_embed(title="Leaderboard")
    lines = []
    for i, row in enumerate(rows, 1):
        member = ctx.guild.get_member(row["user_id"])
        name = member.display_name if member else str(row["user_id"])
        lines.append(f"**{i}.** {name} — {row['total']:,} {CURRENCY_NAME}")
    e.description = "\n".join(lines) if lines else "No data."
    await ctx.send(embed=e)

@bot.command(name="inventory", aliases=["inv"])
async def inventory(ctx, user: discord.Member = None):
    user = user or ctx.author
    with db_connect() as conn:
        rows = conn.execute("SELECT item_name, quantity FROM inventory WHERE user_id=? AND guild_id=?", (user.id, ctx.guild.id)).fetchall()
    e = base_embed(title=f"{user.display_name} — Inventory")
    if rows:
        e.description = "\n".join(f"**{r['item_name']}** x{r['quantity']}" for r in rows)
    else:
        e.description = "Empty."
    await ctx.send(embed=e)

@bot.command(name="shop")
async def shop_cmd(ctx):
    with db_connect() as conn:
        rows = conn.execute("SELECT * FROM shop WHERE guild_id=?", (ctx.guild.id,)).fetchall()
    e = base_embed(title="Shop")
    if rows:
        for r in rows:
            stock = f" | Stock: {r['stock']}" if r["stock"] >= 0 else ""
            e.add_field(name=r["item_name"], value=f"{r['description']}\n**{r['price']:,} {CURRENCY_NAME}**{stock}", inline=False)
    else:
        e.description = "Shop is empty."
    await ctx.send(embed=e)

@bot.command(name="buy")
async def buy(ctx, *, item_name: str):
    with db_connect() as conn:
        item = conn.execute("SELECT * FROM shop WHERE guild_id=? AND LOWER(item_name)=LOWER(?)", (ctx.guild.id, item_name)).fetchone()
    if not item:
        return await ctx.send("Item not found.")
    if item["stock"] == 0:
        return await ctx.send("Out of stock.")
    b = get_balance(ctx.author.id, ctx.guild.id)
    if b["wallet"] < item["price"]:
        return await ctx.send("Not enough balance.")
    with db_connect() as conn:
        conn.execute("UPDATE economy SET wallet=wallet-?, total_spent=total_spent+? WHERE user_id=? AND guild_id=?", (item["price"], item["price"], ctx.author.id, ctx.guild.id))
        if item["stock"] > 0:
            conn.execute("UPDATE shop SET stock=stock-1 WHERE id=?", (item["id"],))
        existing = conn.execute("SELECT id, quantity FROM inventory WHERE user_id=? AND guild_id=? AND item_name=?", (ctx.author.id, ctx.guild.id, item["item_name"])).fetchone()
        if existing:
            conn.execute("UPDATE inventory SET quantity=quantity+1 WHERE id=?", (existing["id"],))
        else:
            conn.execute("INSERT INTO inventory(user_id,guild_id,item_name,quantity) VALUES(?,?,?,1)", (ctx.author.id, ctx.guild.id, item["item_name"]))
    log_transaction(ctx.guild.id, ctx.author.id, f"buy:{item['item_name']}", item["price"])
    await ctx.send(embed=base_embed(description=f"Bought **{item['item_name']}** for {item['price']:,} {CURRENCY_NAME}."))

@bot.command(name="sell")
async def sell(ctx, *, item_name: str):
    with db_connect() as conn:
        inv = conn.execute("SELECT * FROM inventory WHERE user_id=? AND guild_id=? AND LOWER(item_name)=LOWER(?)", (ctx.author.id, ctx.guild.id, item_name)).fetchone()
        if not inv:
            return await ctx.send("You do not have that item.")
        item = conn.execute("SELECT * FROM shop WHERE guild_id=? AND LOWER(item_name)=LOWER(?)", (ctx.guild.id, item_name)).fetchone()
        sell_price = int(item["price"] * 0.5) if item else 50
        if inv["quantity"] <= 1:
            conn.execute("DELETE FROM inventory WHERE id=?", (inv["id"],))
        else:
            conn.execute("UPDATE inventory SET quantity=quantity-1 WHERE id=?", (inv["id"],))
    add_wallet(ctx.author.id, ctx.guild.id, sell_price)
    await ctx.send(embed=base_embed(description=f"Sold **{inv['item_name']}** for **{sell_price:,} {CURRENCY_NAME}**."))

@bot.command(name="use")
async def use_item(ctx, *, item_name: str):
    with db_connect() as conn:
        inv = conn.execute("SELECT * FROM inventory WHERE user_id=? AND guild_id=? AND LOWER(item_name)=LOWER(?)", (ctx.author.id, ctx.guild.id, item_name)).fetchone()
    if not inv:
        return await ctx.send("You do not have that item.")
    await ctx.send(embed=base_embed(description=f"You used **{inv['item_name']}**."))

@bot.command(name="profile")
async def profile(ctx, user: discord.Member = None):
    user = user or ctx.author
    ensure_economy(user.id, ctx.guild.id)
    with db_connect() as conn:
        row = conn.execute("SELECT * FROM economy WHERE user_id=? AND guild_id=?", (user.id, ctx.guild.id)).fetchone()
        warns = conn.execute("SELECT COUNT(*) as c FROM warnings WHERE user_id=? AND guild_id=?", (user.id, ctx.guild.id)).fetchone()["c"]
    e = base_embed(title=f"{user.display_name} — Profile")
    e.add_field(name="Wallet", value=f"{row['wallet']:,}", inline=True)
    e.add_field(name="Bank", value=f"{row['bank']:,}", inline=True)
    e.add_field(name="Total Earned", value=f"{row['total_earned']:,}", inline=True)
    e.add_field(name="Total Spent", value=f"{row['total_spent']:,}", inline=True)
    e.add_field(name="Warnings", value=str(warns), inline=True)
    e.set_thumbnail(url=user.display_avatar.url)
    await ctx.send(embed=e)

@bot.command(name="rob")
async def rob(ctx, target: discord.Member):
    if target.id == ctx.author.id:
        return await ctx.send("You cannot rob yourself.")
    with db_connect() as conn:
        row = conn.execute("SELECT last_rob FROM economy WHERE user_id=? AND guild_id=?", (ctx.author.id, ctx.guild.id)).fetchone()
    cd = on_cooldown(row["last_rob"] if row else 0, 3600)
    if cd:
        return await ctx.send(f"Rob available in {fmt_time(cd)}.")
    tb = get_balance(target.id, ctx.guild.id)
    if tb["wallet"] < 100:
        return await ctx.send("Target has less than 100 in wallet. Not worth it.")
    with db_connect() as conn:
        conn.execute("UPDATE economy SET last_rob=? WHERE user_id=? AND guild_id=?", (int(time.time()), ctx.author.id, ctx.guild.id))
    if random.randint(1, 100) <= 45:
        amount = random.randint(50, min(500, tb["wallet"]))
        add_wallet(target.id, ctx.guild.id, -amount)
        add_wallet(ctx.author.id, ctx.guild.id, amount)
        msg = f"You robbed **{amount:,} {CURRENCY_NAME}** from {target.display_name}."
    else:
        fine = random.randint(100, 300)
        b = get_balance(ctx.author.id, ctx.guild.id)
        fine = min(fine, b["wallet"])
        add_wallet(ctx.author.id, ctx.guild.id, -fine)
        msg = f"You got caught and fined **{fine:,} {CURRENCY_NAME}**."
    await ctx.send(embed=base_embed(description=msg))

@bot.command(name="giveaway")
@commands.has_permissions(manage_guild=True)
async def giveaway(ctx, amount: int):
    if amount <= 0:
        return await ctx.send("Invalid amount.")
    b = get_balance(ctx.author.id, ctx.guild.id)
    if b["wallet"] < amount:
        return await ctx.send("Not enough balance.")
    add_wallet(ctx.author.id, ctx.guild.id, -amount)
    msg = await ctx.send(f"Giveaway! React with ✅ in 30 seconds to enter. Prize: **{amount:,} {CURRENCY_NAME}**")
    await msg.add_reaction("✅")
    await asyncio.sleep(30)
    msg = await ctx.channel.fetch_message(msg.id)
    reaction = discord.utils.get(msg.reactions, emoji="✅")
    users = [u async for u in reaction.users() if not u.bot and u.id != ctx.author.id] if reaction else []
    if not users:
        add_wallet(ctx.author.id, ctx.guild.id, amount)
        return await ctx.send("No entries. Amount returned.")
    winner = random.choice(users)
    add_wallet(winner.id, ctx.guild.id, amount)
    await ctx.send(f"{winner.mention} won **{amount:,} {CURRENCY_NAME}**!")

# ─── GAMES ────────────────────────────────────────────────────────────────────

def validate_bet(ctx, amount: str, min_bet=10, max_bet=50000):
    b = get_balance(ctx.author.id, ctx.guild.id)
    try:
        amt = int(amount)
    except ValueError:
        return None, "Invalid amount."
    if amt < min_bet:
        return None, f"Minimum bet is {min_bet}."
    if amt > max_bet:
        return None, f"Maximum bet is {max_bet:,}."
    if b["wallet"] < amt:
        return None, "Not enough balance."
    return amt, None

def update_game_stats(user_id, guild_id, game, win):
    with db_connect() as conn:
        conn.execute("INSERT OR IGNORE INTO game_stats(user_id,guild_id,game) VALUES(?,?,?)", (user_id, guild_id, game))
        if win:
            conn.execute("UPDATE game_stats SET wins=wins+1 WHERE user_id=? AND guild_id=? AND game=?", (user_id, guild_id, game))
        else:
            conn.execute("UPDATE game_stats SET losses=losses+1 WHERE user_id=? AND guild_id=? AND game=?", (user_id, guild_id, game))

@bot.command(name="coinflip", aliases=["cf"])
async def coinflip(ctx, side: str, amount: str):
    if side.lower() not in ("h", "t", "heads", "tails"):
        return await ctx.send("Choose h or t.")
    amt, err = validate_bet(ctx, amount)
    if err:
        return await ctx.send(err)
    result = random.choice(["h", "t"])
    win = result == side.lower()[0]
    if win:
        add_wallet(ctx.author.id, ctx.guild.id, amt)
        msg = f"Result: **{'Heads' if result=='h' else 'Tails'}**. You won **{amt:,} {CURRENCY_NAME}**."
    else:
        add_wallet(ctx.author.id, ctx.guild.id, -amt)
        msg = f"Result: **{'Heads' if result=='h' else 'Tails'}**. You lost **{amt:,} {CURRENCY_NAME}**."
    update_game_stats(ctx.author.id, ctx.guild.id, "coinflip", win)
    await ctx.send(embed=base_embed(description=msg))

@bot.command(name="slots")
async def slots(ctx, amount: str):
    amt, err = validate_bet(ctx, amount)
    if err:
        return await ctx.send(err)
    symbols = ["🍒", "🍋", "🍊", "⭐", "💎", "7️⃣"]
    weights = [30, 25, 20, 15, 8, 2]
    reels = random.choices(symbols, weights=weights, k=3)
    display = " | ".join(reels)
    if reels[0] == reels[1] == reels[2]:
        multipliers = {"7️⃣": 10, "💎": 7, "⭐": 5, "🍊": 3, "🍋": 2, "🍒": 1.5}
        mult = multipliers.get(reels[0], 2)
        winnings = int(amt * mult)
        add_wallet(ctx.author.id, ctx.guild.id, winnings)
        msg = f"{display}\nJackpot! Won **{winnings:,} {CURRENCY_NAME}**."
        win = True
    elif reels[0] == reels[1] or reels[1] == reels[2]:
        winnings = int(amt * 0.5)
        add_wallet(ctx.author.id, ctx.guild.id, winnings)
        msg = f"{display}\nPartial match! Won **{winnings:,} {CURRENCY_NAME}**."
        win = True
    else:
        add_wallet(ctx.author.id, ctx.guild.id, -amt)
        msg = f"{display}\nNo match. Lost **{amt:,} {CURRENCY_NAME}**."
        win = False
    update_game_stats(ctx.author.id, ctx.guild.id, "slots", win)
    await ctx.send(embed=base_embed(title="Slots", description=msg))

class BlackjackView(discord.ui.View):
    def __init__(self, ctx, amt, player_hand, dealer_hand, deck):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.amt = amt
        self.player_hand = player_hand
        self.dealer_hand = dealer_hand
        self.deck = deck

    def hand_value(self, hand):
        val = 0
        aces = 0
        for card in hand:
            r = card[0]
            if r in ("J", "Q", "K"):
                val += 10
            elif r == "A":
                val += 11
                aces += 1
            else:
                val += int(r) if r != "10" else 10
        while val > 21 and aces:
            val -= 10
            aces -= 1
        return val

    def format_hand(self, hand, hide_second=False):
        if hide_second and len(hand) > 1:
            return f"{hand[0][0]}{hand[0][1]}, ??"
        return ", ".join(f"{c[0]}{c[1]}" for c in hand)

    def build_embed(self, reveal=False):
        pv = self.hand_value(self.player_hand)
        dv = self.hand_value(self.dealer_hand)
        e = base_embed(title="Blackjack")
        e.add_field(name=f"Your Hand ({pv})", value=self.format_hand(self.player_hand), inline=False)
        if reveal:
            e.add_field(name=f"Dealer Hand ({dv})", value=self.format_hand(self.dealer_hand), inline=False)
        else:
            e.add_field(name="Dealer Hand", value=self.format_hand(self.dealer_hand, hide_second=True), inline=False)
        return e

    async def end_game(self, interaction, result):
        pv = self.hand_value(self.player_hand)
        dv = self.hand_value(self.dealer_hand)
        e = self.build_embed(reveal=True)
        if result == "win":
            add_wallet(self.ctx.author.id, self.ctx.guild.id, self.amt)
            e.description = f"You win! +{self.amt:,} {CURRENCY_NAME}"
            e.color = 0x57F287
            update_game_stats(self.ctx.author.id, self.ctx.guild.id, "blackjack", True)
        elif result == "lose":
            add_wallet(self.ctx.author.id, self.ctx.guild.id, -self.amt)
            e.description = f"You lose. -{self.amt:,} {CURRENCY_NAME}"
            e.color = 0xED4245
            update_game_stats(self.ctx.author.id, self.ctx.guild.id, "blackjack", False)
        else:
            e.description = "Push. Bet returned."
        self.stop()
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=e, view=self)

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.green)
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.ctx.author.id:
            return await interaction.response.send_message("Not your game.", ephemeral=True)
        self.player_hand.append(self.deck.pop())
        pv = self.hand_value(self.player_hand)
        if pv > 21:
            return await self.end_game(interaction, "lose")
        elif pv == 21:
            while self.hand_value(self.dealer_hand) < 17:
                self.dealer_hand.append(self.deck.pop())
            dv = self.hand_value(self.dealer_hand)
            result = "win" if dv > 21 or pv > dv else ("lose" if dv > pv else "push")
            return await self.end_game(interaction, result)
        await interaction.response.edit_message(embed=self.build_embed())

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.red)
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.ctx.author.id:
            return await interaction.response.send_message("Not your game.", ephemeral=True)
        while self.hand_value(self.dealer_hand) < 17:
            self.dealer_hand.append(self.deck.pop())
        pv = self.hand_value(self.player_hand)
        dv = self.hand_value(self.dealer_hand)
        if dv > 21 or pv > dv:
            result = "win"
        elif pv == dv:
            result = "push"
        else:
            result = "lose"
        await self.end_game(interaction, result)

@bot.command(name="blackjack", aliases=["bj"])
async def blackjack(ctx, amount: str):
    amt, err = validate_bet(ctx, amount)
    if err:
        return await ctx.send(err)
    suits = ["♠", "♥", "♦", "♣"]
    ranks = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
    deck = [(r, s) for s in suits for r in ranks]
    random.shuffle(deck)
    ph = [deck.pop(), deck.pop()]
    dh = [deck.pop(), deck.pop()]
    view = BlackjackView(ctx, amt, ph, dh, deck)
    await ctx.send(embed=view.build_embed(), view=view)

@bot.command(name="dice")
async def dice(ctx, amount: str):
    amt, err = validate_bet(ctx, amount)
    if err:
        return await ctx.send(err)
    player = random.randint(1, 6)
    bot_roll = random.randint(1, 6)
    if player > bot_roll:
        add_wallet(ctx.author.id, ctx.guild.id, amt)
        msg = f"You rolled **{player}**, bot rolled **{bot_roll}**. You win **{amt:,} {CURRENCY_NAME}**."
        win = True
    elif player < bot_roll:
        add_wallet(ctx.author.id, ctx.guild.id, -amt)
        msg = f"You rolled **{player}**, bot rolled **{bot_roll}**. You lost **{amt:,} {CURRENCY_NAME}**."
        win = False
    else:
        msg = f"Both rolled **{player}**. Tie. Bet returned."
        win = False
    update_game_stats(ctx.author.id, ctx.guild.id, "dice", win)
    await ctx.send(embed=base_embed(description=msg))

@bot.command(name="rps")
async def rps(ctx, choice: str, amount: str):
    choices = {"rock": "scissors", "paper": "rock", "scissors": "paper", "r": "scissors", "p": "rock", "s": "paper"}
    choice_map = {"r": "rock", "p": "paper", "s": "scissors"}
    if choice.lower() not in choices:
        return await ctx.send("Choose rock, paper, or scissors.")
    amt, err = validate_bet(ctx, amount)
    if err:
        return await ctx.send(err)
    player = choice_map.get(choice.lower(), choice.lower())
    bot_choice = random.choice(["rock", "paper", "scissors"])
    if player == bot_choice:
        msg = f"You: {player} | Bot: {bot_choice}. Tie."
        win = False
    elif choices[player] == bot_choice:
        add_wallet(ctx.author.id, ctx.guild.id, amt)
        msg = f"You: {player} | Bot: {bot_choice}. You win **{amt:,} {CURRENCY_NAME}**."
        win = True
    else:
        add_wallet(ctx.author.id, ctx.guild.id, -amt)
        msg = f"You: {player} | Bot: {bot_choice}. You lost **{amt:,} {CURRENCY_NAME}**."
        win = False
    update_game_stats(ctx.author.id, ctx.guild.id, "rps", win)
    await ctx.send(embed=base_embed(description=msg))

# ─── TICKETS ──────────────────────────────────────────────────────────────────

class TicketCreateButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Open Ticket", style=discord.ButtonStyle.blurple, custom_id="ticket_open")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        with db_connect() as conn:
            cfg = conn.execute("SELECT * FROM ticket_config WHERE guild_id=?", (guild.id,)).fetchone()
            open_count = conn.execute("SELECT COUNT(*) as c FROM tickets WHERE guild_id=? AND creator_id=? AND status='open'", (guild.id, interaction.user.id)).fetchone()["c"]
        max_t = cfg["max_tickets"] if cfg else 3
        if open_count >= max_t:
            return await interaction.response.send_message(f"You already have {open_count} open tickets.", ephemeral=True)
        cat_id = cfg["category_id"] if cfg else None
        category = guild.get_channel(cat_id) if cat_id else None
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }
        if cfg and cfg["support_role"]:
            role = guild.get_role(cfg["support_role"])
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        try:
            channel = await guild.create_text_channel(
                name=f"ticket-{interaction.user.name}",
                category=category,
                overwrites=overwrites
            )
        except Exception as e:
            return await interaction.response.send_message("Failed to create ticket channel.", ephemeral=True)
        with db_connect() as conn:
            conn.execute("INSERT INTO tickets(guild_id,channel_id,creator_id,status,created_at) VALUES(?,?,?,?,?)",
                         (guild.id, channel.id, interaction.user.id, "open", int(time.time())))
            ticket_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        close_view = TicketCloseView()
        e = base_embed(title=f"Ticket #{ticket_id}", description=f"Opened by {interaction.user.mention}.\nUse the button below to close.")
        await channel.send(embed=e, view=close_view)
        await interaction.response.send_message(f"Ticket opened: {channel.mention}", ephemeral=True)
        if cfg and cfg["log_channel"]:
            log_ch = guild.get_channel(cfg["log_channel"])
            if log_ch:
                try:
                    await log_ch.send(embed=base_embed(description=f"Ticket #{ticket_id} opened by {interaction.user.mention} in {channel.mention}"))
                except Exception:
                    pass

class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.red, custom_id="ticket_close_btn")
    async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        with db_connect() as conn:
            ticket = conn.execute("SELECT * FROM tickets WHERE channel_id=?", (interaction.channel.id,)).fetchone()
        if not ticket:
            return await interaction.response.send_message("No ticket found here.", ephemeral=True)
        if ticket["creator_id"] != interaction.user.id and not interaction.user.guild_permissions.manage_channels:
            return await interaction.response.send_message("No permission.", ephemeral=True)
        with db_connect() as conn:
            conn.execute("UPDATE tickets SET status='closed', close_reason=? WHERE channel_id=?", ("Closed via button", interaction.channel.id))
        await interaction.channel.edit(name=f"closed-{interaction.channel.name}")
        await interaction.response.send_message("Ticket closed.")

@bot.group(name="ticket", invoke_without_command=True)
async def ticket_group(ctx):
    await ctx.send("Use `Xticket <subcommand>`. See `Xhelp tickets`.")

@ticket_group.command(name="setup")
@commands.has_permissions(manage_guild=True)
async def ticket_setup(ctx, support_role: discord.Role = None, category: discord.CategoryChannel = None, log_channel: discord.TextChannel = None):
    with db_connect() as conn:
        conn.execute("INSERT OR IGNORE INTO ticket_config(guild_id) VALUES(?)", (ctx.guild.id,))
        if support_role:
            conn.execute("UPDATE ticket_config SET support_role=? WHERE guild_id=?", (support_role.id, ctx.guild.id))
        if category:
            conn.execute("UPDATE ticket_config SET category_id=? WHERE guild_id=?", (category.id, ctx.guild.id))
        if log_channel:
            conn.execute("UPDATE ticket_config SET log_channel=? WHERE guild_id=?", (log_channel.id, ctx.guild.id))
    await ctx.send("Ticket system configured.")

@ticket_group.command(name="panel")
@commands.has_permissions(manage_guild=True)
async def ticket_panel(ctx):
    e = base_embed(title="Support Tickets", description="Click the button below to open a ticket.")
    view = TicketCreateButton()
    await ctx.send(embed=e, view=view)

@ticket_group.command(name="add")
@commands.has_permissions(manage_channels=True)
async def ticket_add(ctx, user: discord.Member):
    with db_connect() as conn:
        ticket = conn.execute("SELECT * FROM tickets WHERE channel_id=?", (ctx.channel.id,)).fetchone()
    if not ticket:
        return await ctx.send("Not a ticket channel.")
    await ctx.channel.set_permissions(user, read_messages=True, send_messages=True)
    await ctx.send(f"{user.mention} added to ticket.")

@ticket_group.command(name="remove")
@commands.has_permissions(manage_channels=True)
async def ticket_remove(ctx, user: discord.Member):
    with db_connect() as conn:
        ticket = conn.execute("SELECT * FROM tickets WHERE channel_id=?", (ctx.channel.id,)).fetchone()
    if not ticket:
        return await ctx.send("Not a ticket channel.")
    await ctx.channel.set_permissions(user, overwrite=None)
    await ctx.send(f"{user.mention} removed from ticket.")

@ticket_group.command(name="claim")
async def ticket_claim(ctx):
    with db_connect() as conn:
        ticket = conn.execute("SELECT * FROM tickets WHERE channel_id=?", (ctx.channel.id,)).fetchone()
    if not ticket:
        return await ctx.send("Not a ticket channel.")
    with db_connect() as conn:
        conn.execute("UPDATE tickets SET claimed_by=? WHERE channel_id=?", (ctx.author.id, ctx.channel.id))
    await ctx.send(f"{ctx.author.mention} claimed this ticket.")

@ticket_group.command(name="unclaim")
async def ticket_unclaim(ctx):
    with db_connect() as conn:
        conn.execute("UPDATE tickets SET claimed_by=NULL WHERE channel_id=?", (ctx.channel.id,))
    await ctx.send("Ticket unclaimed.")

@ticket_group.command(name="close")
async def ticket_close(ctx, *, reason: str = None):
    with db_connect() as conn:
        ticket = conn.execute("SELECT * FROM tickets WHERE channel_id=?", (ctx.channel.id,)).fetchone()
    if not ticket:
        return await ctx.send("Not a ticket channel.")
    with db_connect() as conn:
        conn.execute("UPDATE tickets SET status='closed', close_reason=? WHERE channel_id=?", (reason or "No reason", ctx.channel.id))
    await ctx.channel.edit(name=f"closed-{ctx.channel.name}")
    await ctx.send(f"Ticket closed. Reason: {reason or 'No reason.'}")

@ticket_group.command(name="reopen")
async def ticket_reopen(ctx):
    with db_connect() as conn:
        ticket = conn.execute("SELECT * FROM tickets WHERE channel_id=?", (ctx.channel.id,)).fetchone()
    if not ticket:
        return await ctx.send("Not a ticket channel.")
    with db_connect() as conn:
        conn.execute("UPDATE tickets SET status='open' WHERE channel_id=?", (ctx.channel.id,))
    name = ctx.channel.name.replace("closed-", "")
    await ctx.channel.edit(name=name)
    await ctx.send("Ticket reopened.")

@ticket_group.command(name="transcript")
async def ticket_transcript(ctx):
    with db_connect() as conn:
        ticket = conn.execute("SELECT * FROM tickets WHERE channel_id=?", (ctx.channel.id,)).fetchone()
    if not ticket:
        return await ctx.send("Not a ticket channel.")
    lines = [f"Transcript for ticket #{ticket['id']} in {ctx.guild.name}", f"Created: {datetime.datetime.fromtimestamp(ticket['created_at'])}", ""]
    try:
        async for msg in ctx.channel.history(limit=500, oldest_first=True):
            lines.append(f"[{msg.created_at.strftime('%Y-%m-%d %H:%M:%S')}] {msg.author} ({msg.author.id}): {msg.content or '(no text)'}")
    except Exception:
        lines.append("Some messages could not be retrieved.")
    content = "\n".join(lines)
    file = discord.File(io.BytesIO(content.encode()), filename=f"ticket-{ticket['id']}.txt")
    await ctx.send("Transcript:", file=file)

@ticket_group.command(name="logs")
@commands.has_permissions(manage_guild=True)
async def ticket_logs(ctx):
    with db_connect() as conn:
        rows = conn.execute("SELECT * FROM tickets WHERE guild_id=? ORDER BY created_at DESC LIMIT 10", (ctx.guild.id,)).fetchall()
    e = base_embed(title="Recent Tickets")
    if rows:
        lines = []
        for r in rows:
            ch = ctx.guild.get_channel(r["channel_id"])
            ch_str = ch.mention if ch else f"#{r['channel_id']}"
            lines.append(f"**#{r['id']}** — {ch_str} — Status: {r['status']}")
        e.description = "\n".join(lines)
    else:
        e.description = "No tickets."
    await ctx.send(embed=e)

@ticket_group.command(name="config")
@commands.has_permissions(manage_guild=True)
async def ticket_config_view(ctx):
    with db_connect() as conn:
        cfg = conn.execute("SELECT * FROM ticket_config WHERE guild_id=?", (ctx.guild.id,)).fetchone()
    if not cfg:
        return await ctx.send("Not configured.")
    e = base_embed(title="Ticket Config")
    e.add_field(name="Support Role", value=f"<@&{cfg['support_role']}>" if cfg["support_role"] else "None", inline=True)
    e.add_field(name="Max Tickets", value=str(cfg["max_tickets"]), inline=True)
    e.add_field(name="Log Channel", value=f"<#{cfg['log_channel']}>" if cfg["log_channel"] else "None", inline=True)
    await ctx.send(embed=e)

# ─── MODERATION ───────────────────────────────────────────────────────────────

@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
@commands.bot_has_permissions(ban_members=True)
async def ban(ctx, user: discord.Member, *, reason: str = "No reason"):
    if user.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
        return await ctx.send("You cannot ban this user.")
    if user.top_role >= ctx.guild.me.top_role:
        return await ctx.send("I cannot ban this user.")
    await ctx.guild.ban(user, reason=reason, delete_message_days=0)
    case_id = add_mod_case(ctx.guild.id, user.id, ctx.author.id, "ban", reason)
    await ctx.send(embed=base_embed(description=f"Banned {user} | Case #{case_id}"))
    await send_mod_log(ctx.guild, "Ban", user, ctx.author, reason, case_id)

@bot.command(name="unban")
@commands.has_permissions(ban_members=True)
@commands.bot_has_permissions(ban_members=True)
async def unban(ctx, user_id: int, *, reason: str = "No reason"):
    try:
        user = await bot.fetch_user(user_id)
        await ctx.guild.unban(user, reason=reason)
        case_id = add_mod_case(ctx.guild.id, user_id, ctx.author.id, "unban", reason)
        await ctx.send(embed=base_embed(description=f"Unbanned {user} | Case #{case_id}"))
        await send_mod_log(ctx.guild, "Unban", user, ctx.author, reason, case_id)
    except discord.NotFound:
        await ctx.send("User not found or not banned.")

@bot.command(name="kick")
@commands.has_permissions(kick_members=True)
@commands.bot_has_permissions(kick_members=True)
async def kick(ctx, user: discord.Member, *, reason: str = "No reason"):
    if user.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
        return await ctx.send("You cannot kick this user.")
    if user.top_role >= ctx.guild.me.top_role:
        return await ctx.send("I cannot kick this user.")
    await ctx.guild.kick(user, reason=reason)
    case_id = add_mod_case(ctx.guild.id, user.id, ctx.author.id, "kick", reason)
    await ctx.send(embed=base_embed(description=f"Kicked {user} | Case #{case_id}"))
    await send_mod_log(ctx.guild, "Kick", user, ctx.author, reason, case_id)

@bot.command(name="timeout", aliases=["mute"])
@commands.has_permissions(moderate_members=True)
@commands.bot_has_permissions(moderate_members=True)
async def timeout_cmd(ctx, user: discord.Member, duration: str, *, reason: str = "No reason"):
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    try:
        unit = duration[-1].lower()
        val = int(duration[:-1])
        secs = val * multipliers.get(unit, 1)
    except Exception:
        return await ctx.send("Invalid duration. Use format like 10m, 1h, 1d.")
    until = discord.utils.utcnow() + datetime.timedelta(seconds=secs)
    await user.timeout(until, reason=reason)
    case_id = add_mod_case(ctx.guild.id, user.id, ctx.author.id, "timeout", reason)
    await ctx.send(embed=base_embed(description=f"Timed out {user} for {duration} | Case #{case_id}"))
    await send_mod_log(ctx.guild, "Timeout", user, ctx.author, reason, case_id)

@bot.command(name="untimeout", aliases=["unmute"])
@commands.has_permissions(moderate_members=True)
@commands.bot_has_permissions(moderate_members=True)
async def untimeout_cmd(ctx, user: discord.Member):
    await user.timeout(None)
    await ctx.send(embed=base_embed(description=f"Timeout removed for {user}."))

@bot.command(name="warn")
@commands.has_permissions(manage_messages=True)
async def warn(ctx, user: discord.Member, *, reason: str = "No reason"):
    with db_connect() as conn:
        conn.execute("INSERT INTO warnings(guild_id,user_id,moderator_id,reason,timestamp) VALUES(?,?,?,?,?)",
                     (ctx.guild.id, user.id, ctx.author.id, reason, int(time.time())))
        count = conn.execute("SELECT COUNT(*) as c FROM warnings WHERE user_id=? AND guild_id=?", (user.id, ctx.guild.id)).fetchone()["c"]
    case_id = add_mod_case(ctx.guild.id, user.id, ctx.author.id, "warn", reason)
    await ctx.send(embed=base_embed(description=f"Warned {user} | Total warnings: {count} | Case #{case_id}"))
    await send_mod_log(ctx.guild, "Warn", user, ctx.author, reason, case_id)

@bot.command(name="warnings", aliases=["warns"])
async def warnings(ctx, user: discord.Member):
    with db_connect() as conn:
        rows = conn.execute("SELECT * FROM warnings WHERE user_id=? AND guild_id=? ORDER BY timestamp DESC", (user.id, ctx.guild.id)).fetchall()
    e = base_embed(title=f"{user.display_name} — Warnings ({len(rows)})")
    if rows:
        lines = []
        for i, r in enumerate(rows[:10], 1):
            mod = ctx.guild.get_member(r["moderator_id"])
            mod_str = str(mod) if mod else str(r["moderator_id"])
            lines.append(f"**{i}.** {r['reason']} — by {mod_str}")
        e.description = "\n".join(lines)
    else:
        e.description = "No warnings."
    await ctx.send(embed=e)

@bot.command(name="clearwarns")
@commands.has_permissions(manage_messages=True)
async def clearwarns(ctx, user: discord.Member):
    with db_connect() as conn:
        conn.execute("DELETE FROM warnings WHERE user_id=? AND guild_id=?", (user.id, ctx.guild.id))
    await ctx.send(embed=base_embed(description=f"Cleared all warnings for {user}."))

@bot.command(name="purge")
@commands.has_permissions(manage_messages=True)
@commands.bot_has_permissions(manage_messages=True)
async def purge(ctx, amount: int):
    if amount < 1 or amount > 500:
        return await ctx.send("Amount must be between 1 and 500.")
    deleted = await ctx.channel.purge(limit=amount + 1)
    await ctx.send(f"Deleted {len(deleted)-1} messages.", delete_after=5)

@bot.command(name="slowmode")
@commands.has_permissions(manage_channels=True)
@commands.bot_has_permissions(manage_channels=True)
async def slowmode(ctx, seconds: int):
    if seconds < 0 or seconds > 21600:
        return await ctx.send("Slowmode must be 0–21600 seconds.")
    await ctx.channel.edit(slowmode_delay=seconds)
    await ctx.send(f"Slowmode set to {seconds}s.")

@bot.command(name="lock")
@commands.has_permissions(manage_channels=True)
@commands.bot_has_permissions(manage_channels=True)
async def lock(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    await channel.set_permissions(ctx.guild.default_role, send_messages=False)
    await ctx.send(f"{channel.mention} locked.")

@bot.command(name="unlock")
@commands.has_permissions(manage_channels=True)
@commands.bot_has_permissions(manage_channels=True)
async def unlock(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    await channel.set_permissions(ctx.guild.default_role, send_messages=None)
    await ctx.send(f"{channel.mention} unlocked.")

@bot.command(name="hide")
@commands.has_permissions(manage_channels=True)
@commands.bot_has_permissions(manage_channels=True)
async def hide(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    await channel.set_permissions(ctx.guild.default_role, view_channel=False)
    await ctx.send(f"{channel.mention} hidden.")

@bot.command(name="unhide")
@commands.has_permissions(manage_channels=True)
@commands.bot_has_permissions(manage_channels=True)
async def unhide(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    await channel.set_permissions(ctx.guild.default_role, view_channel=None)
    await ctx.send(f"{channel.mention} visible.")

@bot.command(name="nick")
@commands.has_permissions(manage_nicknames=True)
@commands.bot_has_permissions(manage_nicknames=True)
async def nick(ctx, user: discord.Member, *, name: str = None):
    await user.edit(nick=name)
    await ctx.send(f"Nickname {'removed' if not name else f'set to {name}'} for {user}.")

@bot.command(name="role")
@commands.has_permissions(manage_roles=True)
@commands.bot_has_permissions(manage_roles=True)
async def role_cmd(ctx, user: discord.Member, role: discord.Role):
    if role >= ctx.guild.me.top_role:
        return await ctx.send("I cannot manage this role.")
    if role in user.roles:
        await user.remove_roles(role)
        await ctx.send(f"Removed {role.name} from {user}.")
    else:
        await user.add_roles(role)
        await ctx.send(f"Added {role.name} to {user}.")

@bot.command(name="modlog")
@commands.has_permissions(manage_messages=True)
async def modlog(ctx, count: int = 10):
    count = min(count, 25)
    with db_connect() as conn:
        rows = conn.execute("SELECT * FROM mod_cases WHERE guild_id=? ORDER BY timestamp DESC LIMIT ?", (ctx.guild.id, count)).fetchall()
    e = base_embed(title=f"Mod Log — Last {count}")
    if rows:
        lines = []
        for r in rows:
            mod = ctx.guild.get_member(r["moderator_id"])
            mod_str = str(mod) if mod else str(r["moderator_id"])
            lines.append(f"**#{r['id']}** {r['action']} on <@{r['user_id']}> by {mod_str} — {r['reason'] or 'No reason'}")
        e.description = "\n".join(lines)
    else:
        e.description = "No cases."
    await ctx.send(embed=e)

@bot.command(name="case")
async def case(ctx, case_id: int):
    with db_connect() as conn:
        row = conn.execute("SELECT * FROM mod_cases WHERE id=? AND guild_id=?", (case_id, ctx.guild.id)).fetchone()
    if not row:
        return await ctx.send("Case not found.")
    e = base_embed(title=f"Case #{row['id']}")
    e.add_field(name="Action", value=row["action"], inline=True)
    e.add_field(name="User", value=f"<@{row['user_id']}>", inline=True)
    e.add_field(name="Moderator", value=f"<@{row['moderator_id']}>", inline=True)
    e.add_field(name="Reason", value=row["reason"] or "None", inline=False)
    e.add_field(name="Time", value=str(datetime.datetime.fromtimestamp(row["timestamp"])), inline=False)
    await ctx.send(embed=e)

# ─── UTILITY ──────────────────────────────────────────────────────────────────

_start_time = time.time()

@bot.command(name="ping")
async def ping(ctx):
    await ctx.send(embed=base_embed(description=f"Latency: **{round(bot.latency * 1000)}ms**"))

@bot.command(name="uptime")
async def uptime(ctx):
    elapsed = int(time.time() - _start_time)
    await ctx.send(embed=base_embed(description=f"Uptime: **{fmt_time(elapsed)}**"))

@bot.command(name="server", aliases=["serverinfo"])
async def server_info(ctx):
    g = ctx.guild
    e = base_embed(title=g.name)
    e.add_field(name="Owner", value=str(g.owner), inline=True)
    e.add_field(name="Members", value=str(g.member_count), inline=True)
    e.add_field(name="Channels", value=str(len(g.channels)), inline=True)
    e.add_field(name="Roles", value=str(len(g.roles)), inline=True)
    e.add_field(name="Created", value=g.created_at.strftime("%Y-%m-%d"), inline=True)
    if g.icon:
        e.set_thumbnail(url=g.icon.url)
    await ctx.send(embed=e)

@bot.command(name="userinfo", aliases=["ui"])
async def userinfo(ctx, user: discord.Member = None):
    user = user or ctx.author
    e = base_embed(title=str(user))
    e.add_field(name="ID", value=str(user.id), inline=True)
    e.add_field(name="Joined", value=user.joined_at.strftime("%Y-%m-%d") if user.joined_at else "N/A", inline=True)
    e.add_field(name="Created", value=user.created_at.strftime("%Y-%m-%d"), inline=True)
    e.add_field(name="Roles", value=", ".join(r.name for r in user.roles[1:][:10]) or "None", inline=False)
    e.set_thumbnail(url=user.display_avatar.url)
    await ctx.send(embed=e)

@bot.command(name="avatar", aliases=["av"])
async def avatar(ctx, user: discord.Member = None):
    user = user or ctx.author
    e = base_embed(title=f"{user.display_name} — Avatar")
    e.set_image(url=user.display_avatar.url)
    await ctx.send(embed=e)

@bot.command(name="roleinfo")
async def roleinfo(ctx, *, role: discord.Role):
    e = base_embed(title=f"Role — {role.name}")
    e.add_field(name="ID", value=str(role.id), inline=True)
    e.add_field(name="Members", value=str(len(role.members)), inline=True)
    e.add_field(name="Color", value=str(role.color), inline=True)
    e.add_field(name="Hoisted", value=str(role.hoist), inline=True)
    e.add_field(name="Mentionable", value=str(role.mentionable), inline=True)
    e.color = role.color.value
    await ctx.send(embed=e)

@bot.command(name="channelinfo", aliases=["ci"])
async def channelinfo(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    e = base_embed(title=f"#{channel.name}")
    e.add_field(name="ID", value=str(channel.id), inline=True)
    e.add_field(name="Category", value=str(channel.category) if channel.category else "None", inline=True)
    e.add_field(name="NSFW", value=str(channel.is_nsfw()), inline=True)
    if hasattr(channel, "topic") and channel.topic:
        e.add_field(name="Topic", value=channel.topic[:200], inline=False)
    await ctx.send(embed=e)

@bot.command(name="membercount", aliases=["mc"])
async def membercount(ctx):
    g = ctx.guild
    bots = sum(1 for m in g.members if m.bot)
    humans = g.member_count - bots
    e = base_embed(title="Member Count")
    e.add_field(name="Total", value=str(g.member_count), inline=True)
    e.add_field(name="Humans", value=str(humans), inline=True)
    e.add_field(name="Bots", value=str(bots), inline=True)
    await ctx.send(embed=e)

@bot.command(name="poll")
async def poll(ctx, *, question: str):
    e = base_embed(title="Poll", description=question)
    msg = await ctx.send(embed=e)
    await msg.add_reaction("✅")
    await msg.add_reaction("❌")

@bot.command(name="say")
@commands.has_permissions(manage_messages=True)
async def say(ctx, *, message: str):
    await ctx.message.delete()
    await ctx.send(message)

@bot.command(name="embed")
@commands.has_permissions(manage_messages=True)
async def embed_cmd(ctx, *, text: str):
    await ctx.message.delete()
    await ctx.send(embed=base_embed(description=text))

@bot.command(name="remind")
async def remind(ctx, duration: str, *, message: str):
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    try:
        unit = duration[-1].lower()
        val = int(duration[:-1])
        secs = val * multipliers.get(unit, 60)
    except Exception:
        return await ctx.send("Invalid duration. Use format like 10m, 1h.")
    remind_at = int(time.time()) + secs
    with db_connect() as conn:
        conn.execute("INSERT INTO reminders(user_id,channel_id,message,remind_at,created_at) VALUES(?,?,?,?,?)",
                     (ctx.author.id, ctx.channel.id, message, remind_at, int(time.time())))
    await ctx.send(f"Reminder set for {duration} from now.")

@bot.command(name="afk")
async def afk_cmd(ctx, *, reason: str = "AFK"):
    with db_connect() as conn:
        conn.execute("INSERT OR REPLACE INTO afk(user_id,guild_id,reason,set_at) VALUES(?,?,?,?)",
                     (ctx.author.id, ctx.guild.id, reason, int(time.time())))
    await ctx.send(f"{ctx.author.mention} is now AFK: {reason}", delete_after=5)

@bot.command(name="report")
async def report(ctx, user: discord.Member, *, reason: str = "No reason"):
    cfg = get_guild_cfg(ctx.guild.id)
    ch_id = cfg.get("report_channel")
    if not ch_id:
        return await ctx.send("No report channel configured.")
    ch = ctx.guild.get_channel(ch_id)
    if not ch:
        return await ctx.send("Report channel not found.")
    e = base_embed(title="Report", color=0xED4245)
    e.add_field(name="Reported User", value=f"{user} ({user.id})", inline=True)
    e.add_field(name="Reporter", value=f"{ctx.author} ({ctx.author.id})", inline=True)
    e.add_field(name="Reason", value=reason, inline=False)
    e.add_field(name="Channel", value=ctx.channel.mention, inline=True)
    await ch.send(embed=e)
    await ctx.send("Report submitted.", delete_after=5)
    try:
        await ctx.message.delete()
    except Exception:
        pass

@bot.command(name="suggest")
async def suggest(ctx, *, text: str):
    cfg = get_guild_cfg(ctx.guild.id)
    ch_id = cfg.get("suggest_channel")
    if not ch_id:
        return await ctx.send("No suggestion channel configured.")
    ch = ctx.guild.get_channel(ch_id)
    if not ch:
        return await ctx.send("Suggestion channel not found.")
    e = base_embed(title="Suggestion", description=text)
    e.set_footer(text=f"By {ctx.author}")
    msg = await ch.send(embed=e)
    await msg.add_reaction("✅")
    await msg.add_reaction("❌")
    await ctx.send("Suggestion submitted.", delete_after=5)

@bot.command(name="firstmsg")
async def firstmsg(ctx):
    async for msg in ctx.channel.history(limit=1, oldest_first=True):
        await ctx.send(f"First message by {msg.author}: {msg.jump_url}")

@bot.command(name="servericon")
async def servericon(ctx):
    if not ctx.guild.icon:
        return await ctx.send("No server icon.")
    e = base_embed(title=f"{ctx.guild.name} — Icon")
    e.set_image(url=ctx.guild.icon.url)
    await ctx.send(embed=e)

@bot.command(name="serverbanner")
async def serverbanner(ctx):
    if not ctx.guild.banner:
        return await ctx.send("No server banner.")
    e = base_embed(title=f"{ctx.guild.name} — Banner")
    e.set_image(url=ctx.guild.banner.url)
    await ctx.send(embed=e)

@bot.command(name="invite")
async def invite(ctx):
    perms = discord.Permissions(permissions=414539926614)
    url = discord.utils.oauth_url(bot.user.id, permissions=perms)
    await ctx.send(embed=base_embed(description=f"[Invite Link]({url})"))

@bot.command(name="snipe")
async def snipe(ctx):
    with db_connect() as conn:
        row = conn.execute("SELECT * FROM snipe_messages WHERE channel_id=? ORDER BY deleted_at DESC LIMIT 1", (ctx.channel.id,)).fetchone()
    if not row:
        return await ctx.send("Nothing to snipe.")
    e = base_embed(title="Deleted Message")
    e.add_field(name="Author", value=f"{row['author_name']} ({row['author_id']})", inline=True)
    e.add_field(name="Deleted", value=datetime.datetime.fromtimestamp(row["deleted_at"]).strftime("%H:%M:%S"), inline=True)
    e.add_field(name="Content", value=row["content"][:1000] or "(no text)", inline=False)
    await ctx.send(embed=e)

@bot.command(name="editsnipe")
async def editsnipe(ctx):
    with db_connect() as conn:
        row = conn.execute("SELECT * FROM edit_snipe WHERE channel_id=? ORDER BY edited_at DESC LIMIT 1", (ctx.channel.id,)).fetchone()
    if not row:
        return await ctx.send("Nothing to snipe.")
    e = base_embed(title="Edited Message")
    e.add_field(name="Author", value=row["author_name"], inline=True)
    e.add_field(name="Before", value=row["before_content"][:500] or "(no text)", inline=False)
    e.add_field(name="After", value=row["after_content"][:500] or "(no text)", inline=False)
    await ctx.send(embed=e)

# ─── STICKY ───────────────────────────────────────────────────────────────────

@bot.command(name="sticky")
@commands.has_permissions(manage_messages=True)
async def sticky(ctx, *, content: str):
    with db_connect() as conn:
        conn.execute("INSERT OR REPLACE INTO sticky_messages(guild_id,channel_id,content) VALUES(?,?,?)",
                     (ctx.guild.id, ctx.channel.id, content))
    await ctx.send("Sticky set.")

@bot.command(name="unsticky")
@commands.has_permissions(manage_messages=True)
async def unsticky(ctx):
    with db_connect() as conn:
        conn.execute("DELETE FROM sticky_messages WHERE guild_id=? AND channel_id=?", (ctx.guild.id, ctx.channel.id))
    await ctx.send("Sticky removed.")

@bot.command(name="stickies")
async def stickies(ctx):
    with db_connect() as conn:
        rows = conn.execute("SELECT * FROM sticky_messages WHERE guild_id=?", (ctx.guild.id,)).fetchall()
    e = base_embed(title="Sticky Messages")
    if rows:
        lines = [f"<#{r['channel_id']}> — {r['content'][:50]}" for r in rows]
        e.description = "\n".join(lines)
    else:
        e.description = "None."
    await ctx.send(embed=e)

# ─── LOGGING CONFIG ───────────────────────────────────────────────────────────

@bot.group(name="log", invoke_without_command=True)
@commands.has_permissions(manage_guild=True)
async def log_group(ctx):
    await ctx.send("Use `Xlog setup <channel>` or `Xlog config`.")

@log_group.command(name="setup")
@commands.has_permissions(manage_guild=True)
async def log_setup(ctx, channel: discord.TextChannel):
    set_guild_cfg(ctx.guild.id, log_channel=channel.id)
    await ctx.send(f"Log channel set to {channel.mention}.")

@log_group.command(name="config")
@commands.has_permissions(manage_guild=True)
async def log_config(ctx):
    cfg = get_guild_cfg(ctx.guild.id)
    e = base_embed(title="Log Config")
    e.add_field(name="Log Channel", value=f"<#{cfg['log_channel']}>" if cfg.get("log_channel") else "None", inline=True)
    e.add_field(name="Mod Log Channel", value=f"<#{cfg['mod_log_channel']}>" if cfg.get("mod_log_channel") else "None", inline=True)
    e.add_field(name="Welcome Channel", value=f"<#{cfg['welcome_channel']}>" if cfg.get("welcome_channel") else "None", inline=True)
    e.add_field(name="Leave Channel", value=f"<#{cfg['leave_channel']}>" if cfg.get("leave_channel") else "None", inline=True)
    await ctx.send(embed=e)

@log_group.command(name="test")
@commands.has_permissions(manage_guild=True)
async def log_test(ctx):
    await send_log(ctx.guild, "Log Test", f"Test event triggered by {ctx.author}.")
    await ctx.send("Test log sent.")

# ─── WELCOME CONFIG ───────────────────────────────────────────────────────────

@bot.group(name="welcome", invoke_without_command=True)
@commands.has_permissions(manage_guild=True)
async def welcome_group(ctx):
    await ctx.send("Use `Xwelcome channel <ch>` or `Xwelcome message <msg>`.")

@welcome_group.command(name="channel")
@commands.has_permissions(manage_guild=True)
async def welcome_channel(ctx, channel: discord.TextChannel):
    set_guild_cfg(ctx.guild.id, welcome_channel=channel.id)
    await ctx.send(f"Welcome channel set to {channel.mention}.")

@welcome_group.command(name="message")
@commands.has_permissions(manage_guild=True)
async def welcome_message(ctx, *, message: str):
    set_guild_cfg(ctx.guild.id, welcome_message=message)
    await ctx.send("Welcome message set.")

@welcome_group.command(name="leave")
@commands.has_permissions(manage_guild=True)
async def welcome_leave(ctx, channel: discord.TextChannel):
    set_guild_cfg(ctx.guild.id, leave_channel=channel.id)
    await ctx.send(f"Leave channel set to {channel.mention}.")

# ─── ANTI-NUKE COMMANDS ───────────────────────────────────────────────────────

@bot.group(name="antinuke", aliases=["an"], invoke_without_command=True)
@commands.has_permissions(manage_guild=True)
async def antinuke_group(ctx):
    await ctx.send("Use `Xantinuke <subcommand>`. See `Xhelp security`.")

@antinuke_group.command(name="setup")
@commands.has_permissions(manage_guild=True)
async def an_setup(ctx, log_channel: discord.TextChannel = None):
    get_antinuke_cfg(ctx.guild.id)
    if log_channel:
        set_guild_cfg(ctx.guild.id, antinuke_log_channel=log_channel.id)
    await ctx.send("Anti-nuke configured. Use `Xantinuke enable` to activate.")

@antinuke_group.command(name="enable")
@commands.has_permissions(manage_guild=True)
async def an_enable(ctx):
    with db_connect() as conn:
        conn.execute("INSERT OR IGNORE INTO antinuke_config(guild_id) VALUES(?)", (ctx.guild.id,))
        conn.execute("UPDATE antinuke_config SET enabled=1 WHERE guild_id=?", (ctx.guild.id,))
    await ctx.send("Anti-nuke enabled.")

@antinuke_group.command(name="disable")
@commands.has_permissions(manage_guild=True)
async def an_disable(ctx):
    with db_connect() as conn:
        conn.execute("UPDATE antinuke_config SET enabled=0 WHERE guild_id=?", (ctx.guild.id,))
    await ctx.send("Anti-nuke disabled.")

@antinuke_group.command(name="status")
async def an_status(ctx):
    cfg = get_antinuke_cfg(ctx.guild.id)
    e = base_embed(title="Anti-Nuke Status")
    e.add_field(name="Enabled", value=str(bool(cfg["enabled"])), inline=True)
    e.add_field(name="Action", value=cfg["action"], inline=True)
    e.add_field(name="Time Window", value=f"{cfg['time_window']}s", inline=True)
    e.add_field(name="Channel Delete Limit", value=str(cfg["channel_delete_limit"]), inline=True)
    e.add_field(name="Role Delete Limit", value=str(cfg["role_delete_limit"]), inline=True)
    e.add_field(name="Ban Limit", value=str(cfg["ban_limit"]), inline=True)
    await ctx.send(embed=e)

@antinuke_group.command(name="config")
@commands.has_permissions(manage_guild=True)
async def an_config(ctx, key: str, value: str):
    valid_keys = ["channel_delete_limit", "channel_create_limit", "role_delete_limit",
                  "role_create_limit", "ban_limit", "kick_limit", "webhook_limit",
                  "time_window", "action", "lockdown_duration"]
    if key not in valid_keys:
        return await ctx.send(f"Invalid key. Valid: {', '.join(valid_keys)}")
    if key == "action" and value not in ("kick", "ban", "strip"):
        return await ctx.send("Action must be kick, ban, or strip.")
    with db_connect() as conn:
        if key == "action":
            conn.execute(f"UPDATE antinuke_config SET {key}=? WHERE guild_id=?", (value, ctx.guild.id))
        else:
            try:
                conn.execute(f"UPDATE antinuke_config SET {key}=? WHERE guild_id=?", (int(value), ctx.guild.id))
            except ValueError:
                return await ctx.send("Value must be a number.")
    await ctx.send(f"Set {key} to {value}.")

@antinuke_group.command(name="whitelist")
@commands.has_permissions(manage_guild=True)
async def an_whitelist(ctx, entity: Union[discord.Member, int]):
    entity_id = entity.id if hasattr(entity, "id") else entity
    with db_connect() as conn:
        conn.execute("INSERT OR IGNORE INTO antinuke_whitelist(guild_id,entity_id) VALUES(?,?)", (ctx.guild.id, entity_id))
    await ctx.send(f"Whitelisted {entity_id}.")

@antinuke_group.command(name="unwhitelist")
@commands.has_permissions(manage_guild=True)
async def an_unwhitelist(ctx, entity_id: int):
    with db_connect() as conn:
        conn.execute("DELETE FROM antinuke_whitelist WHERE guild_id=? AND entity_id=?", (ctx.guild.id, entity_id))
    await ctx.send(f"Removed {entity_id} from whitelist.")

@antinuke_group.group(name="whitelist", invoke_without_command=True)
@commands.has_permissions(manage_guild=True)
async def an_wl_group(ctx):
    pass

@antinuke_group.command(name="logs")
@commands.has_permissions(manage_guild=True)
async def an_logs(ctx):
    with db_connect() as conn:
        rows = conn.execute("SELECT * FROM antinuke_logs WHERE guild_id=? ORDER BY timestamp DESC LIMIT 10", (ctx.guild.id,)).fetchall()
    e = base_embed(title="Security Logs")
    if rows:
        lines = []
        for r in rows:
            t = datetime.datetime.fromtimestamp(r["timestamp"]).strftime("%m/%d %H:%M")
            lines.append(f"**{r['event_type']}** by <@{r['actor_id']}> — {r['action_taken']} ({t})")
        e.description = "\n".join(lines)
    else:
        e.description = "No logs."
    await ctx.send(embed=e)

@antinuke_group.command(name="lockdown")
@commands.has_permissions(manage_guild=True)
async def an_lockdown(ctx):
    locked = []
    for ch in ctx.guild.text_channels:
        try:
            await ch.set_permissions(ctx.guild.default_role, send_messages=False)
            locked.append(ch.id)
        except Exception:
            pass
    await ctx.send(f"Lockdown active. Locked {len(locked)} channels.")

@antinuke_group.command(name="unlock")
@commands.has_permissions(manage_guild=True)
async def an_unlock(ctx):
    count = 0
    for ch in ctx.guild.text_channels:
        try:
            await ch.set_permissions(ctx.guild.default_role, send_messages=None)
            count += 1
        except Exception:
            pass
    await ctx.send(f"Lockdown lifted. Unlocked {count} channels.")

@antinuke_group.command(name="backup")
@commands.has_permissions(manage_guild=True)
async def an_backup(ctx, *, label: str = None):
    data = await take_snapshot(ctx.guild)
    if label:
        with db_connect() as conn:
            conn.execute("UPDATE server_snapshots SET label=? WHERE guild_id=? AND id=(SELECT MAX(id) FROM server_snapshots WHERE guild_id=?)",
                         (label, ctx.guild.id, ctx.guild.id))
    await ctx.send(f"Backup taken. {len(data['channels'])} channels, {len(data['roles'])} roles saved.")

@antinuke_group.command(name="restore")
@commands.has_permissions(manage_guild=True)
async def an_restore(ctx, snapshot_id: int = None):
    with db_connect() as conn:
        if snapshot_id:
            row = conn.execute("SELECT * FROM server_snapshots WHERE id=? AND guild_id=?", (snapshot_id, ctx.guild.id)).fetchone()
        else:
            row = conn.execute("SELECT * FROM server_snapshots WHERE guild_id=? ORDER BY created_at DESC LIMIT 1", (ctx.guild.id,)).fetchone()
    if not row:
        return await ctx.send("No snapshot found.")
    data = json.loads(row["snapshot_data"])
    restored_channels = 0
    restored_roles = 0
    existing_channel_names = {ch.name for ch in ctx.guild.channels}
    for ch_data in data["channels"]:
        if ch_data["name"] not in existing_channel_names:
            try:
                ch_type = ch_data.get("type", "text_channel")
                if "text" in ch_type:
                    await ctx.guild.create_text_channel(name=ch_data["name"])
                    restored_channels += 1
            except Exception:
                pass
    existing_role_names = {r.name for r in ctx.guild.roles}
    for r_data in data["roles"]:
        if r_data["name"] not in existing_role_names:
            try:
                await ctx.guild.create_role(
                    name=r_data["name"],
                    permissions=discord.Permissions(r_data["permissions"]),
                    color=discord.Color(r_data["color"]),
                    hoist=r_data["hoist"],
                    mentionable=r_data["mentionable"]
                )
                restored_roles += 1
            except Exception:
                pass
    await ctx.send(f"Restore complete. {restored_channels} channels, {restored_roles} roles recreated.\nNote: Original IDs cannot be restored. Integrations may require manual repair.")

@antinuke_group.command(name="test")
@commands.has_permissions(manage_guild=True)
async def an_test(ctx):
    cfg = get_guild_cfg(ctx.guild.id)
    log_ch_id = cfg.get("antinuke_log_channel")
    if not log_ch_id:
        return await ctx.send("Set a log channel first with `Xantinuke setup #channel`.")
    ch = ctx.guild.get_channel(log_ch_id)
    if not ch:
        return await ctx.send("Log channel not found.")
    e = base_embed(title="Security Alert — TEST", color=0xFF0000)
    e.description = "This is a test alert. Anti-nuke is working."
    await ch.send(embed=e)
    await ctx.send("Test alert sent.")

# ─── OWNER COMMANDS ───────────────────────────────────────────────────────────

@bot.group(name="owner", invoke_without_command=True)
@is_owner()
async def owner_group(ctx):
    await ctx.send("Owner commands: status, servers, leave, shutdown, blacklist, unblacklist, addcurrency, removecurrency, resetbalance.")

@owner_group.command(name="status")
@is_owner()
async def owner_status(ctx):
    e = base_embed(title="Bot Status")
    e.add_field(name="Servers", value=str(len(bot.guilds)), inline=True)
    e.add_field(name="Users", value=str(sum(g.member_count for g in bot.guilds)), inline=True)
    e.add_field(name="Latency", value=f"{round(bot.latency*1000)}ms", inline=True)
    e.add_field(name="Uptime", value=fmt_time(int(time.time()-_start_time)), inline=True)
    await ctx.send(embed=e)

@owner_group.command(name="servers")
@is_owner()
async def owner_servers(ctx):
    lines = [f"**{g.name}** ({g.id}) — {g.member_count} members" for g in bot.guilds]
    e = base_embed(title="Servers", description="\n".join(lines[:20]))
    await ctx.send(embed=e)

@owner_group.command(name="leave")
@is_owner()
async def owner_leave(ctx, guild_id: int):
    g = bot.get_guild(guild_id)
    if not g:
        return await ctx.send("Guild not found.")
    name = g.name
    await g.leave()
    await ctx.send(f"Left {name}.")

@owner_group.command(name="shutdown")
@is_owner()
async def owner_shutdown(ctx):
    msg = await ctx.send("Confirm shutdown with `yes` within 10 seconds.")
    def check(m): return m.author.id == ctx.author.id and m.content.lower() == "yes" and m.channel == ctx.channel
    try:
        await bot.wait_for("message", check=check, timeout=10)
        await ctx.send("Shutting down.")
        await bot.close()
    except asyncio.TimeoutError:
        await msg.edit(content="Shutdown cancelled.")

@owner_group.command(name="blacklist")
@is_owner()
async def owner_blacklist(ctx, user_id: int):
    with db_connect() as conn:
        conn.execute("INSERT OR IGNORE INTO blacklist(user_id) VALUES(?)", (user_id,))
    await ctx.send(f"Blacklisted {user_id}.")

@owner_group.command(name="unblacklist")
@is_owner()
async def owner_unblacklist(ctx, user_id: int):
    with db_connect() as conn:
        conn.execute("DELETE FROM blacklist WHERE user_id=?", (user_id,))
    await ctx.send(f"Removed {user_id} from blacklist.")

@owner_group.command(name="addcurrency")
@is_owner()
async def owner_addcurrency(ctx, user: discord.Member, amount: int):
    if amount <= 0:
        return await ctx.send("Invalid amount.")
    add_wallet(user.id, ctx.guild.id, amount)
    log_transaction(ctx.guild.id, user.id, f"owner_add by {ctx.author.id}", amount)
    await ctx.send(f"Added {amount:,} {CURRENCY_NAME} to {user}.")

@owner_group.command(name="removecurrency")
@is_owner()
async def owner_removecurrency(ctx, user: discord.Member, amount: int):
    if amount <= 0:
        return await ctx.send("Invalid amount.")
    add_wallet(user.id, ctx.guild.id, -amount)
    log_transaction(ctx.guild.id, user.id, f"owner_remove by {ctx.author.id}", -amount)
    await ctx.send(f"Removed {amount:,} {CURRENCY_NAME} from {user}.")

@owner_group.command(name="resetbalance")
@is_owner()
async def owner_resetbalance(ctx, user: discord.Member):
    msg = await ctx.send(f"Confirm reset of {user}'s balance? Reply `yes` within 10s.")
    def check(m): return m.author.id == ctx.author.id and m.content.lower() == "yes" and m.channel == ctx.channel
    try:
        await bot.wait_for("message", check=check, timeout=10)
        with db_connect() as conn:
            conn.execute("UPDATE economy SET wallet=0, bank=0 WHERE user_id=? AND guild_id=?", (user.id, ctx.guild.id))
        log_transaction(ctx.guild.id, user.id, f"owner_reset by {ctx.author.id}", 0)
        await ctx.send(f"Reset {user}'s balance.")
    except asyncio.TimeoutError:
        await msg.edit(content="Cancelled.")

@owner_group.command(name="maintenance")
@is_owner()
async def owner_maintenance(ctx):
    await ctx.send("Maintenance mode toggled (visual only — restart bot to fully apply).")

# ─── ANTISPAM CONFIG ──────────────────────────────────────────────────────────

@bot.group(name="antispam", invoke_without_command=True)
@commands.has_permissions(manage_guild=True)
async def antispam_group(ctx):
    await ctx.send("Use `Xantispam enable` or `Xantispam disable`.")

@antispam_group.command(name="enable")
@commands.has_permissions(manage_guild=True)
async def antispam_enable(ctx):
    set_guild_cfg(ctx.guild.id, antispam_enabled=1)
    await ctx.send("Anti-spam enabled.")

@antispam_group.command(name="disable")
@commands.has_permissions(manage_guild=True)
async def antispam_disable(ctx):
    set_guild_cfg(ctx.guild.id, antispam_enabled=0)
    await ctx.send("Anti-spam disabled.")

# ─── SHOP ADMIN ───────────────────────────────────────────────────────────────

@bot.group(name="shopconfig", invoke_without_command=True)
@commands.has_permissions(manage_guild=True)
async def shopconfig_group(ctx):
    await ctx.send("Use `Xshopconfig add`, `Xshopconfig remove`, `Xshopconfig list`.")

@shopconfig_group.command(name="add")
@commands.has_permissions(manage_guild=True)
async def shop_add(ctx, price: int, stock: int, *, name_and_desc: str):
    parts = name_and_desc.split("|", 1)
    name = parts[0].strip()
    desc = parts[1].strip() if len(parts) > 1 else "No description"
    with db_connect() as conn:
        conn.execute("INSERT INTO shop(guild_id,item_name,description,price,stock) VALUES(?,?,?,?,?)",
                     (ctx.guild.id, name, desc, price, stock))
    await ctx.send(f"Added **{name}** to shop for {price:,} {CURRENCY_NAME}.")

@shopconfig_group.command(name="remove")
@commands.has_permissions(manage_guild=True)
async def shop_remove(ctx, *, item_name: str):
    with db_connect() as conn:
        conn.execute("DELETE FROM shop WHERE guild_id=? AND LOWER(item_name)=LOWER(?)", (ctx.guild.id, item_name))
    await ctx.send(f"Removed **{item_name}** from shop.")

@shopconfig_group.command(name="list")
@commands.has_permissions(manage_guild=True)
async def shop_list(ctx):
    with db_connect() as conn:
        rows = conn.execute("SELECT * FROM shop WHERE guild_id=?", (ctx.guild.id,)).fetchall()
    e = base_embed(title="Shop Items")
    if rows:
        e.description = "\n".join(f"**{r['item_name']}** — {r['price']:,} | Stock: {'∞' if r['stock']<0 else r['stock']}" for r in rows)
    else:
        e.description = "Empty."
    await ctx.send(embed=e)

# ─── LOG CHANNEL CONFIGS ──────────────────────────────────────────────────────

@bot.command(name="setmodlog")
@commands.has_permissions(manage_guild=True)
async def setmodlog(ctx, channel: discord.TextChannel):
    set_guild_cfg(ctx.guild.id, mod_log_channel=channel.id)
    await ctx.send(f"Mod log channel set to {channel.mention}.")

@bot.command(name="setreports")
@commands.has_permissions(manage_guild=True)
async def setreports(ctx, channel: discord.TextChannel):
    set_guild_cfg(ctx.guild.id, report_channel=channel.id)
    await ctx.send(f"Report channel set to {channel.mention}.")

@bot.command(name="setsuggestions")
@commands.has_permissions(manage_guild=True)
async def setsuggestions(ctx, channel: discord.TextChannel):
    set_guild_cfg(ctx.guild.id, suggest_channel=channel.id)
    await ctx.send(f"Suggestion channel set to {channel.mention}.")

# ─── ERROR HANDLER ────────────────────────────────────────────────────────────

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingPermissions):
        return await ctx.send("You do not have permission.")
    if isinstance(error, commands.BotMissingPermissions):
        return await ctx.send("I do not have permission.")
    if isinstance(error, commands.MissingRequiredArgument):
        return await ctx.send(f"Missing argument: `{error.param.name}`.")
    if isinstance(error, commands.BadArgument):
        return await ctx.send("Invalid argument.")
    if isinstance(error, commands.CommandOnCooldown):
        return await ctx.send(f"Cooldown. Try again in {fmt_time(int(error.retry_after))}.")
    if isinstance(error, commands.CheckFailure):
        return
    print(f"Unhandled error in {ctx.command}: {error}")
    traceback.print_exception(type(error), error, error.__traceback__)

# ─── RUN ──────────────────────────────────────────────────────────────────────

if not TOKEN:
    print("ERROR: DISCORD_TOKEN not set. Create a .env file with DISCORD_TOKEN=your_token_here")
    exit(1)

bot.run(TOKEN)
