import os
import discord
from discord.ext import commands, tasks
from openai import AsyncOpenAI
import aiohttp
import io
import pypdf
import glob
from database import db
from dotenv import load_dotenv
import json

from noelle import NoelleAgent
from emma import EmmaAgent

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OWNER_ID = int(os.getenv("OWNER_ID", "0")) # Your discord User ID to restrict access

# Setup OpenRouter client
client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

# Initialize Sub-Agents
noelle_agent = NoelleAgent(api_key=OPENROUTER_API_KEY)
emma_agent = EmmaAgent(api_key=OPENROUTER_API_KEY)

# Setup Discord bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

SYSTEM_PROMPT = """
You are The Operator, an autonomous daily worker and Social Media Operations Manager.
Your goal is to assist your owner with their business operations, providing crisp, actionable advice.
Use the context provided from 'The Vault' to tailor your responses.
Keep your answers direct, without fluff or 'guru-speak'.
"""

def load_static_vault():
    """Load markdown files from the local /vault directory into the database"""
    for filepath in glob.glob("vault/*.md"):
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            # Basic chunking by double newline for paragraphs
            chunks = content.split('\n\n')
            for chunk in chunks:
                if chunk.strip():
                    db.add_to_vault(chunk.strip(), os.path.basename(filepath))
    print("Static vault files loaded.")

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
    load_static_vault()
    daily_standup.start()
    emma_daily_brief.start()

async def get_ai_response(user_id, user_message):
    history = db.get_history(user_id)
    
    # Retrieve relevant context from vault
    search_results = db.search_vault(user_message, top_k=3)
    vault_context = "\n".join([f"Source ({res[2]}):\n{res[1]}" for res in search_results])
    
    context_prompt = f"Relevant context from The Vault:\n{vault_context}\n\nUser Message: {user_message}"
    
    if not history:
        history.append({"role": "system", "content": SYSTEM_PROMPT})
        
    history.append({"role": "user", "content": context_prompt})
    
    response = await client.chat.completions.create(
        model="deepseek/deepseek-chat", # DeepSeek V3 on OpenRouter
        messages=history,
    )
    
    ai_message = response.choices[0].message.content
    
    # Store the actual user message (not the prompt injected one) and AI response
    # Re-fetch and clean up the appended user message
    history.pop()
    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": ai_message})
    
    # Keep history manageable (e.g., last 20 messages + system prompt)
    if len(history) > 21:
        history = [history[0]] + history[-20:]
        
    db.update_history(user_id, history)
    
    return ai_message

@bot.command(name='save')
async def save_to_vault(ctx):
    if ctx.author.id != OWNER_ID and OWNER_ID != 0:
        return
        
    if not ctx.message.attachments:
        await ctx.send("Please attach a PDF or text file with the `!save` command.")
        return
        
    attachment = ctx.message.attachments[0]
    
    if attachment.filename.endswith('.pdf'):
        async with aiohttp.ClientSession() as session:
            async with session.get(attachment.url) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    pdf_file = io.BytesIO(data)
                    reader = pypdf.PdfReader(pdf_file)
                    text = ""
                    for page in reader.pages:
                        text += page.extract_text() + "\n\n"
                    
                    # Basic chunking
                    chunks = text.split('\n\n')
                    for chunk in chunks:
                        if chunk.strip():
                            db.add_to_vault(chunk.strip(), attachment.filename)
                    
                    await ctx.send(f"Saved PDF {attachment.filename} to The Vault.")
    else:
        await ctx.send("Currently only PDF files are supported for dynamic vault saving.")

@bot.command(name='noelle')
async def call_noelle(ctx, *, request: str):
    if ctx.author.id != OWNER_ID and OWNER_ID != 0:
        return
    await ctx.send("🎨 **Noelle:** Processing your media request...")
    try:
        files = await noelle_agent.run(request)
        if files:
            discord_files = [discord.File(f) for f in files]
            await ctx.send("Here are your generated assets:", files=discord_files)
        else:
            await ctx.send("Noelle completed the request but no files were generated.")
    except Exception as e:
        await ctx.send(f"Error during Noelle generation: {e}")

@bot.command(name='emma')
async def call_emma(ctx):
    if ctx.author.id != OWNER_ID and OWNER_ID != 0:
        return
    await ctx.send("📋 **Emma:** Fetching your executive briefing...")
    try:
        briefing = await emma_agent.generate_briefing()
        # Chunk if needed
        for i in range(0, len(briefing), 2000):
            await ctx.send(briefing[i:i+2000])
    except Exception as e:
        await ctx.send(f"Error generating Emma briefing: {e}")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
        
    if message.author.id != OWNER_ID and OWNER_ID != 0:
        return

    # Process commands like !save
    await bot.process_commands(message)
    
    # If it's a command, don't pass it to the LLM
    if message.content.startswith('!'):
        return
        
    async with message.channel.typing():
        # Step 1: Intent Routing
        # Use a cheap fast model to detect if this is a media request
        router_prompt = """
        You are an intent router. Read the user's message.
        If the user is asking to generate, create, make, or design an image, picture, graphic, flyer, poster, audio, voiceover, or video, output exactly: 'NOELLE'.
        Otherwise, output exactly: 'NORMAL'.
        """
        router_response = await client.chat.completions.create(
            model="openai/gpt-4o-mini",
            messages=[
                {"role": "system", "content": router_prompt},
                {"role": "user", "content": message.content}
            ],
            max_tokens=10
        )
        intent = router_response.choices[0].message.content.strip().upper()
        
        if "NOELLE" in intent:
            await message.channel.send("🎨 **JB:** I'm handing this over to Noelle...")
            try:
                files = await noelle_agent.run(message.content)
                if files:
                    discord_files = [discord.File(f) for f in files]
                    await message.channel.send("Here are your generated assets:", files=discord_files)
                else:
                    await message.channel.send("Noelle completed the request but no files were generated.")
            except Exception as e:
                await message.channel.send(f"Error during Noelle generation: {e}")
            return

        # Step 2: Normal JB Response
        response = await get_ai_response(message.author.id, message.content)
        
        # Discord messages are limited to 2000 chars, so chunk the response if needed
        for i in range(0, len(response), 2000):
            await message.channel.send(response[i:i+2000])

@tasks.loop(hours=24)
async def daily_standup():
    if OWNER_ID == 0:
        print("No OWNER_ID set, skipping daily standup.")
        return
        
    # In a real scenario, you'd fetch the user to DM.
    # For simplicity, if we don't have a specific channel, we might need a channel ID.
    try:
        user = await bot.fetch_user(OWNER_ID)
        if user:
            prompt = "Generate my daily standup. What are the top 3 moves for today based on recent context?"
            response = await get_ai_response(OWNER_ID, prompt)
            await user.send(f"🌅 **Morning Standup Briefing**\n\n{response}")
    except Exception as e:
        print(f"Error sending standup: {e}")

@tasks.loop(hours=24)
async def emma_daily_brief():
    # Configure to run around 6:00 AM. 
    # For now, it will run exactly 24 hours from startup.
    if OWNER_ID == 0:
        return
    try:
        user = await bot.fetch_user(OWNER_ID)
        if user:
            briefing = await emma_agent.generate_briefing()
            for i in range(0, len(briefing), 2000):
                await user.send(briefing[i:i+2000])
    except Exception as e:
        print(f"Error sending Emma briefing: {e}")

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("Please set the DISCORD_TOKEN environment variable.")
    else:
        bot.run(DISCORD_TOKEN)
