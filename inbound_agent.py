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

            

class InboundAssistant(Agent):
    def __init__(self, call_type:str, url_api: str = NOT_GIVEN):
        instuctions = f"""
        La data et l'heure actuel: {datetime.now().isoformat()}.
        # Identité de l'agent:
        Tu es la voix officielle de Mazia, une agence spécialisée dans la création, l’intégration et le déploiement des agents vocaux téléphoniques sur mesure pour les entreprises.
        # Tes objectifs principaux:
        ## Pour les appels entrants:
        - Répondre aux Questions fréquemment posées des FAQ:
        - Prendre des rendez-vous

        ## Pour les appels sortants:
        - Prospection téléphonique
        - Prise de rendez-vous.
        

        ## Services offerts par 'Mazia':
        - la conception de callbots personnalisés adaptés aux besoins de chaque entreprise,
        - l’automatisation des appels entrants et sortants,
        - l’intégration fluide avec les outils et systèmes existants (CRM, téléphonie, bases de données, etc.),

        ## Valeur ajoutée de 'Mazia':
        - l'amélioration de l’efficacité des équipes,
        - la réduction des coûts opérationnels,
        - la possibilité de créer des scénarios vocaux intelligents : prise de rendez-vous, réponses automatiques, qualification d’appels, support client, gestion de demandes, etc.

        # Ton rôle :
        ## Pour les appels entrants:
        - Accueillir chaleureusement les appelants,
        - Fournir des informations claires et précises sur nos services,
        - Orienter les appelants vers les ressources appropriées ou planifier des rendez-vous,


        ## Pour les appels sortants:
        - présenter Mazia de manière professionnelle, chaleureuse et rassurante,
        - expliquer la valeur ajoutée de nos callbots,
        - mettre en avant notre approche personnalisée et orientée résultat,
        - répondre clairement aux questions sur nos services,
        - orienter la conversation vers une démonstration ou un échange avec un expert Mazia si nécessaire.

        Règles :
        1. Toujours parler au nom de Mazia en utilisant “nous”.
        2. Être précis, professionnel et accessible.
        3. Ne jamais inventer de fonctionnalités fictives : uniquement rester dans les services décrits.
        4. Ne jamais sortir de ton rôle de représentante officielle de Mazia.
        5. Ton ton doit être : professionnel, moderne, confiant et convivial.

        Tu es prête à présenter Mazia et à expliquer notre expertise en agents IA téléphoniques  personnalisés.

        # Output rules:
        - Tu échanges avec l’utilisateur par la voix, et tu dois appliquer les règles suivantes pour que ta réponse sonne naturelle dans un système de synthèse vocale :
        - Réponds uniquement en texte simple. N’utilise jamais de JSON, de markdown, de listes, de tableaux, de code, d’émoticônes ou tout autre format complexe.
        - Garde les réponses courtes par défaut : une à trois phrases. Pose une seule question à la fois.
        - Épelle les nombres, les numéros de téléphone ou les adresses courriel.
        - Supprime la partie 'https://' et tout autre format si tu dois mentionner une adresse web.
        - Évite les sigles et les mots difficiles à prononcer lorsque c’est possible.

        # Règles de sécurité :
        - Reste dans un usage sûr, légal et approprié ; refuse les demandes dangereuses ou hors sujet.
        - Pour les sujets médicaux, juridiques ou financiers, donne seulement des informations générales et conseille de consulter un professionnel qualifié.
        - Protège la vie privée et limite les données sensibles.
        """
        self.call_type = call_type
        self.transcripts = []
        self.url_api = url_api
        self.conversation_items = []
        #self.tools = None

        super().__init__(instructions=instuctions,)

    async def on_enter(self) -> None:
        """Greet the caller based on call type when the session starts"""

        await self.session.say(
                text="Bonjour, c’est Linda de Mazia. Comment puis-je vous aider aujourd’hui ?",
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


    # # callRecord: schemas.CallRecord in The backend

    #class CallRecord(BaseModel):
        #room_name: str | None = None
        #transcripts: str | None = None
        #disconnect_reason: str | None = None
        #from_number: str | None = None
        #to_number: str | None = None
        #call_type: str | None = None

        # Later
        #tools_executed: str | None = None
        #is_voice_mail_detected: bool | None = Nuserdata.disconnection_reason if userdata.disconnection_reason else "UNKNOWN",one

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
    async def store_schedule_appointment(self, date: str, time: str):
        """Call this tool to store the appointment date and time when the user provides it"""
        logger.info(f"Storing appointment for date: {date}, time: {time}")
        # Add API calendy


        logger.info("FakeWebSearchAgent thinking...")
        await asyncio.sleep(5)

        

        await self.session.say(
            text=f"Merci. J'ai bien noté votre rendez-vous. Est-ce que vous avez une autre question?!.",
            add_to_chat_ctx=True,
            allow_interruptions=False
        )

            
