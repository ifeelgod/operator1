@bot.command(name='noelle')
async def call_noelle(ctx, *, user_request: str = None):
    if ctx.author.id != OWNER_ID and OWNER_ID != 0:
        return
    if not user_request:
        await ctx.send(get_agent_menu("noelle"))
        return
    await ctx.send("🎨 **Noelle:** Processing your media request...")
    try:
        files = await noelle_agent.run(user_request)
        if files:
            discord_files = [discord.File(f) for f in files]
            await ctx.send(files=discord_files)
        else:
            await ctx.send("Noelle could not generate the media.")
    except Exception as e:
        await ctx.send(f"Error generating media: {e}")

@bot.command(name='linda')
async def call_linda(ctx, *, user_request: str = None):
    if ctx.author.id != OWNER_ID and OWNER_ID != 0:
        return
    if not user_request:
        await ctx.send(get_agent_menu("linda"))
        return
    await ctx.send("💼 **Linda:** Processing your operations request...")
    try:
        response = await linda_agent.run(user_request)
        await ctx.send(response)
    except Exception as e:
        await ctx.send(f"Error contacting Linda: {e}")

@bot.command(name='emma')
async def call_emma(ctx, *, user_request: str = None):
    if ctx.author.id != OWNER_ID and OWNER_ID != 0:
        return
    if not user_request or "briefing" not in user_request.lower():
        await ctx.send(get_agent_menu("emma"))
        return
    await ctx.send("📋 **Emma:** Fetching your executive briefing...")
    try:
        briefing = await emma_agent.generate_briefing()
        for i in range(0, len(briefing), 2000):
            await ctx.send(briefing[i:i+2000])
    except Exception as e:
        await ctx.send(f"Error generating Emma briefing: {e}")

@bot.command(name='standup')
async def call_standup(ctx):
    if ctx.author.id != OWNER_ID and OWNER_ID != 0:
        return
    await ctx.send("🛠️ **JB:** Generating your internal project standup...")
    try:
        prompt = "Generate my daily standup. What are the top 3 moves for today based on recent internal project context?"
        response = await get_ai_response(ctx.author.id, prompt)
        for i in range(0, len(response), 2000):
            await ctx.send(response[i:i+2000])
    except Exception as e:
        await ctx.send(f"Error generating standup: {e}")

@bot.command(name='morning')
async def call_morning(ctx):
    if ctx.author.id != OWNER_ID and OWNER_ID != 0:
        return
    await ctx.send("🌅 **JB:** Good morning! Syncing with Emma to build your ultimate briefing...")
    try:
        emma_briefing = await emma_agent.generate_briefing()
        prompt = f"""
        I need my ultimate morning briefing. 
        Here is Emma's external Chief of Staff briefing:
        ---
        {emma_briefing}
        ---
        Combine Emma's external triage with my internal project context. Format it as one cohesive, executive Morning Briefing.
        """
        response = await get_ai_response(ctx.author.id, prompt)
        for i in range(0, len(response), 2000):
            await ctx.send(response[i:i+2000])
    except Exception as e:
        await ctx.send(f"Error generating morning briefing: {e}")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
        
    bare_msg = message.content.strip().lower()
    bare_commands = ["jb", "!jb", "emma", "!emma", "noelle", "!noelle", "linda", "!linda", "david", "!david"]
    
    if bare_msg in bare_commands:
        agent_name = bare_msg.replace("!", "")
        await message.channel.send(get_agent_menu(agent_name))
        return

    if message.author.id != OWNER_ID and OWNER_ID != 0:
        return

    await bot.process_commands(message)
    
    if message.content.startswith('!'):
        return
        
    async with message.channel.typing():
        user_message = message.content
        router_prompt = f"""
        You are an intent router. 
        If the user is asking to create, draw, generate, or make an image, video, flyer, ad, or audio voiceover, reply with exactly the word "NOELLE".
        If the user is asking to log an expense, send an invoice, bill a client, track household spending, or do accounting, reply with exactly the word "LINDA".
        Otherwise, reply with exactly the word "JB".
        User message: "{user_message}"
        """
        router_response = await get_ai_response(OWNER_ID, router_prompt)
        intent = router_response.strip().upper()
        
        if "NOELLE" in intent:
            await message.channel.send("🎨 **JB:** I'm handing this over to Noelle...")
            try:
                files = await noelle_agent.run(user_message)
                if files:
                    discord_files = [discord.File(f) for f in files]
                    await message.channel.send(files=discord_files)
                else:
                    await message.channel.send("Noelle could not generate the media.")
            except Exception as e:
                await message.channel.send(f"Error generating media: {e}")
            return
            
        if "LINDA" in intent:
            await message.channel.send("💼 **Linda:** Processing your operations request...")
            try:
                response = await linda_agent.run(user_message)
                await message.channel.send(response)
            except Exception as e:
                await message.channel.send(f"Error contacting Linda: {e}")
            return

        response = await get_ai_response(message.author.id, message.content)
        for i in range(0, len(response), 2000):
            await message.channel.send(response[i:i+2000])

@tasks.loop(hours=24)
async def daily_standup():
    if OWNER_ID == 0:
        return
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