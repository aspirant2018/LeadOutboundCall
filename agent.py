import logging
from datetime import datetime
from dotenv import load_dotenv
from livekit.agents import (
    NOT_GIVEN,
    Agent,
    AgentFalseInterruptionEvent,
    AgentSession,
    JobContext,
    JobProcess,
    MetricsCollectedEvent,
    RoomInputOptions,
    RunContext,
    WorkerOptions,
    cli,
    metrics,
    get_job_context,
    ChatContext,
    CloseEvent,
    
)
from livekit import rtc, api
from livekit.agents.llm import function_tool
from livekit.plugins import cartesia, deepgram, noise_cancellation, openai, silero, elevenlabs
from livekit.plugins.turn_detector.multilingual import MultilingualModel
import os
from livekit.agents.llm import ToolError
from dataclasses import dataclass
import asyncio
from livekit.agents import AgentTask, function_tool
import requests
import logging
import aiohttp
import asyncio
import json
from dataclasses import  asdict
from datetime import datetime
from zoneinfo import ZoneInfo
from livekit import api
from livekit.protocol.sip import SIPCallInfo


logger = logging.getLogger("main")


async def hangup_call():
    ctx = get_job_context()
    if ctx is None:
        # Not running in a job context
        return
    await ctx.api.room.delete_room(
        api.DeleteRoomRequest(
            room=ctx.room.name,
        )
    )

class Assistant(Agent):
    def __init__(self):
        instuctions = f"""
        la data et l'heure actuel: {datetime.now().isoformat()}
        Tu es la voix officielle de Voix-Up, une agence spécialisée dans la création, l’intégration et le déploiement de call-bots professionnels et sur mesure pour les entreprises.

        Ta mission est d’expliquer clairement et simplement ce que fait Voix-Up, en mettant en avant :
        - la conception de callbots personnalisés adaptés aux besoins de chaque entreprise,
        - l’automatisation des appels entrants et sortants,
        - l'amélioration de l’efficacité des équipes,
        - la réduction des coûts opérationnels,
        - l’intégration fluide avec les outils et systèmes existants (CRM, téléphonie, bases de données, etc.),
        - la possibilité de créer des scénarios vocaux intelligents : prise de rendez-vous, réponses automatiques, qualification d’appels, support client, gestion de demandes, etc.

        Ton rôle :
        - présenter VoixUp de manière professionnelle, chaleureuse et rassurante,
        - expliquer la valeur ajoutée de nos callbots,
        - mettre en avant notre approche personnalisée et orientée résultat,
        - répondre clairement aux questions sur nos services,
        - orienter la conversation vers une démonstration ou un échange avec un expert VoixUp si nécessaire.

        Règles :
        1. Toujours parler au nom de VoixUp en utilisant “nous”.
        2. Être précis, professionnel et accessible.
        3. Ne jamais inventer de fonctionnalités fictives : uniquement rester dans les services décrits.
        4. Ne jamais sortir de ton rôle de représentante officielle de VoixUp.
        5. Ton ton doit être : professionnel, moderne, confiant et convivial.

        Tu es prête à présenter VoixUp et à expliquer notre expertise en callbots personnalisés.
        """
        super().__init__(instructions=instuctions)

    async def on_enter(self) -> None:
        await self.session.say(
            text="Bonjour, c’est Linda de Voix-Up. Merci pour votre intérêt ! J’aimerais comprendre vos besoins pour voir comment notre solution peut vous aider. Est-ce que vous avez une minute ?")      
    
    @function_tool
    async def end_call(self, ctx: RunContext):
        """Called when the user wants to end the call"""
        await ctx.wait_for_playout() # let the agent finish speaking
        await hangup_call()

    @function_tool
    async def detected_answering_machine(self):
        """Call this tool if you have detected a voicemail system, AFTER hearing the voicemail greeting"""
        await self.session.generate_reply(
            instructions="Leave a voicemail message letting the user know you'll call back later."
        )
        await asyncio.sleep(0.5) # Add a natural gap to the end of the voicemail message
        await hangup_call()


            
