import os
import aiohttp
from pydantic import BaseModel, Field
from typing import Literal, Optional
from openai import AsyncOpenAI
import json

class LindaRequest(BaseModel):
    action_type: Literal["invoice", "expense", "other"] = Field(..., description="The type of financial action requested.")
    client_name: Optional[str] = Field(None, description="The name of the client to invoice, if applicable.")
    client_email: Optional[str] = Field(None, description="The email of the client to invoice, if applicable.")
    amount: Optional[float] = Field(None, description="The dollar amount of the expense or invoice.")
    category: Optional[str] = Field(None, description="The category of the expense (e.g., household, internet, marketing) or the item being invoiced.")
    notes: Optional[str] = Field(None, description="Any additional context or description.")

class LindaAgent:
    def __init__(self, api_key: str):
        self.client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )
        self.webhook_url = os.environ.get("N8N_LINDA_WEBHOOK_URL")

        self.system_prompt = """
        You are Linda, an operations and accounting agent.
        Your job is to parse the user's natural language request into a strict JSON payload.
        You handle two primary actions: 'invoice' (billing clients via PayPal) and 'expense' (logging household or business expenses into Google Sheets).
        If the user provides an amount, extract it as a number.
        If the user provides a client name or email, extract it.
        """

    async def parse_request(self, user_request: str) -> LindaRequest:
        schema_str = json.dumps(LindaRequest.model_json_schema())
        full_system_prompt = self.system_prompt + f"\n\nYou MUST return ONLY valid JSON that matches this exact schema:\n{schema_str}"
        
        response = await self.client.chat.completions.create(
            model="openai/gpt-4o-mini",
            messages=[
                {"role": "system", "content": full_system_prompt},
                {"role": "user", "content": user_request}
            ],
            response_format={"type": "json_object"}
        )
        
        raw_json = response.choices[0].message.content
        return LindaRequest.model_validate_json(raw_json)

    async def run(self, user_request: str) -> str:
        if not self.webhook_url:
            return "❌ N8N_LINDA_WEBHOOK_URL is not set in the environment variables."
            
        try:
            # 1. Parse the request into structured JSON
            plan = await self.parse_request(user_request)
            
            # 2. Send the structured JSON to n8n
            payload = plan.model_dump()
            print("Linda executing payload:", payload)
            
            async with aiohttp.ClientSession() as session:
                async with session.post(self.webhook_url, json=payload) as resp:
                    if resp.status == 200:
                        n8n_response = await resp.text()
                        if n8n_response.strip() and n8n_response.strip() != "Webhook received":
                            return f"💼 **Linda:** {n8n_response}"
                        return f"💼 **Linda:** Successfully dispatched the `{plan.action_type}` request to n8n operations!"
                    else:
                        return f"💼 **Linda:** Error contacting n8n operations (Status: {resp.status})."
                        
        except Exception as e:
            print(f"Linda error: {e}")
            return f"💼 **Linda:** I ran into an error processing that financial request: {e}"
