import os
import io
import pytz
import discord
from discord.ext import commands, tasks
from datetime import time
import asyncio
from openai import AsyncOpenAI
import database

# Configuration & Secrets
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
ALLOWED_USER_ID = int(os.getenv("DISCORD_USER_ID", "0"))
TIMEZONE = os.getenv("TIMEZONE", "America/Chicago")

# Initialize OpenRouter Async Client
ai_client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

SYSTEM_PROMPT = """
You are The Operator, your name is Apex — the Daily Social Media Operations Manager.
Your mission: Keep the creator in their zone of genius (on-camera, strategy, closing) and out of the weeds.

Who You Work For:
- Business: High-ticket digital marketing & web hosting for local business owners & creators.
- Voice: Direct, punchy, practical, zero fluff, zero guru-speak.

When asked for a Standup, follow the 4-part format:
1. TOP 3-5 MOVES TODAY
2. DO-MYSELF LIST
3. DELEGATE LIST
4. ONE FOCUS

Use any provided "Vault Context" to make your answers hyper-specific to the brand.
"""

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

def get_augmented_prompt(user_input: str) -> str:
    """Retrieve relevant vault chunks and construct the final prompt."""
    results = database.search_vault(user_input, top_k=3)
    if not results:
        return user_input
        
    context_str = "\n".join([f"[{r['source']}] {r['chunk']}" for r in results])
    augmented = f"VAULT CONTEXT:\n{context_str}\n\nUSER PROMPT:\n{user_input}"
    return augmented

async def ask_operator(user_id: str, user_message: str) -> str:
    # 1. Save user message to history
    database.add_message(user_id, "user", user_message)
    
    # 2. Get past history
    history = database.get_conversation_history(user_id, limit=10)
    
    # 3. Augment the latest message with RAG
    augmented_msg = get_augmented_prompt(user_message)
    
    # 4. Build OpenAI messages array
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    # Add history (excluding the current one which is augmented)
    for msg in history[:-1]:
        messages.append({"role": msg["role"], "content": msg["content"]})
        
    messages.append({"role": "user", "content": augmented_msg})

    try:
        response = await ai_client.chat.completions.create(
            model="deepseek/deepseek-chat",
            messages=messages,
            temperature=0.7,
        )
        reply = response.choices[0].message.content
        
        # Save assistant reply to history
        database.add_message(user_id, "assistant", reply)
        return reply
    except Exception as e:
        return f"❌ Error communicating with OpenRouter: {str(e)}"

# ---------------- BOT EVENTS & COMMANDS ---------------- #

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')
    
    # Ingest static vault files on startup
    vault_dir = "./vault"
    if os.path.exists(vault_dir):
        for filename in os.listdir(vault_dir):
            if filename.endswith(".md") or filename.endswith(".txt"):
                filepath = os.path.join(vault_dir, filename)
                with open(filepath, 'r', encoding='utf-8') as f:
                    text = f.read()
                    chunks = database.add_to_vault(filename, text)
                print(f"Ingested {filename} ({chunks} chunks)")
    
    scheduled_morning_brief.start()

@bot.command(name="standup")
async def standup_cmd(ctx):
    if ctx.author.id != ALLOWED_USER_ID:
        return
        
    async with ctx.typing():
        await ctx.send("☕ Crunching today's operational priorities...")
        brief = await ask_operator(str(ctx.author.id), "Generate today's operational standup. Give me high-leverage moves.")
        
        # Discord has a 2000 char limit, chunk if necessary
        for i in range(0, len(brief), 2000):
            await ctx.send(brief[i:i+2000])

@bot.command(name="save")
async def save_cmd(ctx):
    if ctx.author.id != ALLOWED_USER_ID:
        return
        
    if not ctx.message.attachments:
        await ctx.send("Please attach a text or markdown file with the `!save` command.")
        return
        
    for attachment in ctx.message.attachments:
        if attachment.filename.endswith(('.txt', '.md')):
            file_bytes = await attachment.read()
            text = file_bytes.decode('utf-8')
            chunks = database.add_to_vault(attachment.filename, text)
            await ctx.send(f"✅ Saved `{attachment.filename}` to The Vault ({chunks} chunks).")
        else:
            await ctx.send(f"⚠️ Skipping `{attachment.filename}`: Only .txt and .md supported for now.")

@bot.event
async def on_message(message):
    # Ignore own messages
    if message.author == bot.user:
        return
        
    # Process commands first
    if message.content.startswith('!'):
        await bot.process_commands(message)
        return
        
    # Only respond to the allowed user in DM or if mentioned in a server
    if message.author.id != ALLOWED_USER_ID:
        return
        
    if isinstance(message.channel, discord.DMChannel) or bot.user in message.mentions:
        async with message.channel.typing():
            # Remove mention from text if present
            text = message.content.replace(f'<@{bot.user.id}>', '').strip()
            reply = await ask_operator(str(message.author.id), text)
            
            for i in range(0, len(reply), 2000):
                await message.channel.send(reply[i:i+2000])

# ---------------- SCHEDULED DAILY PUSH ---------------- #

tz = pytz.timezone(TIMEZONE)
brief_time = time(hour=7, minute=0, second=0, tzinfo=tz)

@tasks.loop(time=brief_time)
async def scheduled_morning_brief():
    try:
        user = await bot.fetch_user(ALLOWED_USER_ID)
        if user:
            brief = await ask_operator(str(ALLOWED_USER_ID), "Generate the official morning standup for today.")
            await user.send(f"🌅 **Morning Standup Briefing**\n\n")
            for i in range(0, len(brief), 2000):
                await user.send(brief[i:i+2000])
    except Exception as e:
        print(f"Error sending scheduled brief: {e}")

if __name__ == "__main__":
    if not DISCORD_BOT_TOKEN:
        print("Missing DISCORD_BOT_TOKEN environment variable.")
    else:
        bot.run(DISCORD_BOT_TOKEN)
