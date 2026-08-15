import asyncio
import aiohttp
import uuid
import os
import urllib.parse
from pydantic import BaseModel, Field
from typing import List, Literal, Optional
from openai import AsyncOpenAI
import edge_tts

# --- Pydantic Data Models ---
class ImageRequest(BaseModel):
    prompt: str = Field(..., description="The highly detailed visual prompt for the image. Optimize for Pollinations.ai (stable diffusion style prompts).")
    aspect_ratio: Literal["1:1", "16:9", "9:16"] = Field(..., description="The aspect ratio of the image.")
    category: Literal["image", "graphic", "flyer"] = Field(..., description="The type of visual asset.")

class AudioRequest(BaseModel):
    script: str = Field(..., description="The script to be spoken. Must contain NO markdown, asterisks, or visual cues. Just spoken text.")
    voice: Literal["en-US-ChristopherNeural", "en-US-AriaNeural", "en-GB-SoniaNeural", "en-US-GuyNeural"] = Field(default="en-US-ChristopherNeural", description="The voice actor to use.")

class MediaPlan(BaseModel):
    images: List[ImageRequest] = Field(default_factory=list)
    audio: List[AudioRequest] = Field(default_factory=list)


# --- Noelle Agent Class ---
class NoelleAgent:
    def __init__(self, api_key: str):
        self.client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )
        
        self.system_prompt = """
        You are Noelle, a media development and design agent.
        Your goal is to parse the user's creative requests and output a strict JSON media plan.
        You have access to a free Image generator (Pollinations.ai) and a free Neural Voice generator (Edge-TTS).
        
        Rules:
        - If the user asks for a flyer, ad, or picture, create an ImageRequest.
        - If the user asks for a voiceover, script, or audio, create an AudioRequest.
        - If they ask for a video, inform them through the audio script that you currently only support static visuals and voiceovers, and generate a corresponding image and audio instead.
        - NEVER include markdown like **bold** in the audio script.
        - Make your image prompts extremely descriptive, including lighting, style, and camera angles.
        """

    async def generate_media_plan(self, user_request: str) -> MediaPlan:
        """Calls OpenRouter to get the structured Pydantic MediaPlan."""
        # Note: OpenRouter supports structured outputs with models like gpt-4o or claude-3-5-sonnet.
        # We will use openai/gpt-4o-mini as a fast, cheap router if available, or just standard JSON mode.
        response = await self.client.chat.completions.create(
            model="openai/gpt-4o-mini", # Extremely cheap and fast structured output
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_request}
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "media_plan",
                    "schema": MediaPlan.model_json_schema(),
                    "strict": True
                }
            }
        )
        
        raw_json = response.choices[0].message.content
        return MediaPlan.model_validate_json(raw_json)

    async def execute_image(self, req: ImageRequest) -> str:
        """Executes the Pollinations.ai image generation and saves it to disk."""
        print(f"Generating Image: {req.prompt}")
        encoded_prompt = urllib.parse.quote(req.prompt)
        
        # Determine width/height based on aspect ratio
        width, height = 1024, 1024
        if req.aspect_ratio == "16:9":
            width, height = 1280, 720
        elif req.aspect_ratio == "9:16":
            width, height = 720, 1280
            
        url = f"https://pollinations.ai/p/{encoded_prompt}?width={width}&height={height}&nologo=true"
        
        filename = f"vault/noelle_img_{uuid.uuid4().hex[:8]}.png"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    with open(filename, 'wb') as f:
                        f.write(await resp.read())
                    return filename
        return None

    async def execute_audio(self, req: AudioRequest) -> str:
        """Executes Edge-TTS generation and saves to disk."""
        print(f"Generating Audio with voice {req.voice}...")
        filename = f"vault/noelle_audio_{uuid.uuid4().hex[:8]}.mp3"
        communicate = edge_tts.Communicate(req.script, req.voice)
        await communicate.save(filename)
        return filename

    async def run(self, user_request: str) -> List[str]:
        """Runs the entire Noelle pipeline and returns a list of generated file paths."""
        plan = await self.generate_media_plan(user_request)
        print("Media Plan Generated:", plan)
        
        tasks = []
        for img in plan.images:
            tasks.append(self.execute_image(img))
        for aud in plan.audio:
            tasks.append(self.execute_audio(aud))
            
        results = await asyncio.gather(*tasks)
        # Filter out None
        return [r for r in results if r]
