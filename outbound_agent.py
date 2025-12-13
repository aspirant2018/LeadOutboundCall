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

# Next 
# Defining 2 agents: one for inbound calls, one for outbound calls
# Both agents share the same behavior, but the greeting message is different and inbound agent does not have the answering machine tool


class OutboundAssistant(Agent):
    def __init__(self,fname,lname,email,phone_number, url_api:str = NOT_GIVEN):
        
        self.transcripts = []
        self.url_api = url_api
        self.conversation_items = []
        
        self.fname = fname
        self.lname = lname
        self.email = email
        self.phone_number = phone_number
        
        instuctions = f"""
        La data et l'heure actuel: {datetime.now().isoformat()}.
        # Identité:
        Tu es la voix officielle de Mazia, une agence spécialisée dans la création, l’intégration et le déploiement d’agents vocaux téléphoniques sur mesure pour les entreprises.
        
        les informations sur l'interlocuteur: 
        - Nom: {self.lname}
        - Prénom: {self.fname}
        - Email: {self.email}


        # Role:
        Tu gères des appels sortants à destination de professionnels, décideurs ou responsables métiers.
        Ta mission est de présenter Mazia de manière professionnelle et crédible, d’identifier rapidement l’intérêt du prospect et d’orienter l’échange vers une prise de rendez-vous pour une démonstration avec un expert Mazia.
        Tu expliques clairement notre proposition de valeur pour les entreprises :
            - automatisation intelligente des appels entrants et sortants
            - réduction de la charge opérationnelle des équipes
            - amélioration de la réactivité client et intégration fluide avec les outils existants comme les systèmes de relation client et la téléphonie.
        
        Tu adoptes une posture de conseil, jamais agressive ni insistante. Ton objectif n’est pas de vendre immédiatement mais de qualifier l’intérêt et de proposer un échange approfondi.

        # Gestion des objections :
        Si l’interlocuteur dit qu’il n’a pas le temps, tu acknowledges brièvement et proposes une alternative courte ou un rendez-vous à un moment plus adapté.
        Si l’interlocuteur dit qu’il n’est pas intéressé, tu demandes poliment si le sujet des agents vocaux ou de l’automatisation des appels est déjà couvert en interne.
        Si l’interlocuteur dit qu’il a déjà une solution, tu valorises l’existant et expliques que Mazia intervient souvent en complément ou en amélioration de solutions en place.
        Si l’interlocuteur exprime une méfiance envers les appels commerciaux, tu te montres transparente, rappelles brièvement la valeur métier et proposes d’arrêter l’appel immédiatement si le sujet ne le concerne pas.
        Si l’interlocuteur demande le prix, tu expliques que les solutions sont sur mesure et que la tarification dépend des usages, puis tu proposes un échange rapide pour évaluer les besoins.

        # Règles de comportement :
        Tu parles toujours au nom de Mazia en utilisant “nous”.
        Tu restes professionnelle, calme, confiante et respectueuse.
        Tu ne promets jamais de fonctionnalités non décrites.
        Tu ne forces jamais la conversation ni la prise de rendez-vous.
        Tu ne sors jamais de ton rôle de représentante officielle de Mazia.

        # Règles de réponse vocale :
        Tu réponds uniquement en texte simple, naturel pour la synthèse vocale.
        Tes réponses sont courtes, une à trois phrases.
        Tu poses une seule question à la fois.
        Tu épelles les nombres, numéros de téléphone et adresses courriel.
        Tu évites les sigles et les mots difficiles à prononcer.
        Tu supprimes “https” si tu mentionnes une adresse web.
        Tés réponses ne devraient pas dépasser 15 mots pour chaque réponse
        """


        super().__init__(instructions=instuctions)

    async def on_enter(self) -> None:
        """Greet the caller based on call type when the session starts"""

        await self.session.say(
                    text=f"Bonjour {self.fname} {self.lname}, c’est Linda de Mazia. Merci pour votre intérêt ! J’aimerais comprendre vos besoins pour voir comment notre solution peut vous aider. Est-ce que vous avez une minute ?",
                    add_to_chat_ctx=True,
                    allow_interruptions=False,
                    )

        # Set up event listeners
        # add transcript listener  
        # Add conversation item listener
        @self.session.on("conversation_item_added")
        def on_conversation_item_added(item):
            logger.info(f"Conversation item added: {item.item}")
            self.conversation_items.append(item)
        

        @self.session.on("metrics_collected")
        def on_metrics_collected(ev: MetricsCollectedEvent):
            #logger.info(f"Metrics collected: {ev.metrics}")
            pass
            
        @self.session.on("speech_created")
        def on_speech_created(speech):
            logger.info(f"Speech created: {speech.text}")

        @self.session.on("close")
        def on_close(ev: CloseEvent):
            logger.info(f"Session is closing {ev}")
            logger.info(f"Type of disconnection: {ev.reason}")
            
            self.disconnect_reason = ev.reason.name  
            logger.info(f"Agent disconnect reason {self.disconnect_reason}")
        
        @self.session.on("function_tools_executed")
        def on_function_tools_executed(tools):
            logger.info(f"Function tools executed: {tools}")
            self.tools.append(tools)
            
    async def on_exit(self) -> None:
        """send transcripts to API on session exit"""
        logger.info("Session is exiting, sending transcripts to API")
        await self._send_transcripts_to_api()             

    async def _send_transcripts_to_api(self):
        """Sends the call transcripts to an external API endpoint"""

        userdata = self.session.userdata  
        logger.info(f"Job metadata: {userdata}")

        if not self.conversation_items:
            # Sometimes there are no conversation items if the callee did not talk at all
            logger.info(f"Number of conversation items to process: 0")
            transcibed_texts = "No conversation items were recorded."
 
        else:
            logger.info(f"Number of conversation items to process: {len(self.conversation_items)}")
            transcibed_texts = ""
            for message in self.conversation_items:
                logger.info(f"Processing conversation item: {message.item}")
                role = "AGENT" if message.item.role == "assistant" else "USER"
                timestamp = message.item.created_at
                text = message.item.content[-1]
                transcibed_texts += f"'{timestamp}' {role}: {text}\n"
            
        payload = {  
            "room_name": userdata.room_name,
            "transcription": transcibed_texts,
            "disconnect_reason": userdata.disconnection_reason if userdata.disconnection_reason else "UNKNOWN",
            "from_number": userdata.from_number,  
            "to_number": userdata.to_number,  
            "call_type": userdata.call_type
        }  
        logger.info(f"Sending transcripts payload: {payload}")
        try:  
            async with aiohttp.ClientSession() as session:  
                async with session.post(  
                    self.url_api,  
                    json=payload,  
                    timeout=aiohttp.ClientTimeout(total=10)  
                ) as response:  
                    if response.status == 200:  
                        print(f"Successfully sent {len(self.transcripts)} transcripts")  
                    else:  
                        print(f"Failed to send transcripts: {response.status}")  
        except Exception as e:  
            print(f"Error sending transcripts to API: {e}")  

    
    # Only used for outbound calls
    @function_tool
    async def detected_answering_machine(self):
        """Call this tool if you have detected a voicemail system, AFTER hearing the voicemail greeting"""
        await self.session.say(
            text="Bonjour, c’est Linda de Mazia. Je vous contacte pour vous présenter nos solutions des agents vocaux téléphoniques  personnalisés qui peuvent grandement améliorer l’efficacité de votre service client. N’hésitez pas à nous rappeler au 01 23 45 67 89 pour en savoir plus. Merci et bonne journée!",
            add_to_chat_ctx=True,
        )
        await asyncio.sleep(0.5) # Add a natural gap to the end of the voicemail message
        await hangup_call()
    

    @function_tool
    async def hungup_call(self,ctx: RunContext):
        """Call this tool when you detect that the callee wants to hang up the call like saying 'goodbye' or 'thank you, goodbye'"""
        await ctx.wait_for_playout() # let the agent finish speaking
        ctx.userdata.disconnection_reason = "AGENT_ENDED_CALL"
        await self.session.say(
            text="Merci pour votre temps. N'hésitez pas à nous contacter si vous avez des questions supplémentaires. Au revoir!",
            add_to_chat_ctx=True,
            allow_interruptions=False
        )
        await hangup_call()


    @function_tool
    async def store_schedule_appointment(self,date: str, time: str):
        """Call this tool to store the appointment date and time when the user provides it"""
        logger.info(f"Storing appointment for date: {date}, time: {time}")
        # Add API calendy

        logger.info("")
        await self.session.say(
            text=f"Merci {self.fname} {self.lname}. J'ai bien noté votre rendez-vous. Est-ce que vous avez une autre question?!.",
            add_to_chat_ctx=True,
            allow_interruptions=False
        )

        await hangup_call()
