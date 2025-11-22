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
from agent import Assistant
logger = logging.getLogger("main")

load_dotenv("/home/raymond/Projects/LeadOutbountCaller/.env.local")
outbound_trunk_id = os.getenv("SIP_OUTBOUND_TRUNK_ID")



def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


@dataclass
class UserData:
    is_availale: bool = None
    date: str = None
    time: str = None


@dataclass
class MetaData:
    call_id: str = None
    created_at: str  = None
    ended_at: str = None
    from_number : str = None
    to_number: str = None
    call_type: str = None
    duration_seconds: float = None
    disconnection_reason: str = None



async def entrypoint(ctx: JobContext):

    userdata = UserData()
    metadata = MetaData()

    logger.info(f"connecting to room '{ctx.room.name}'") # room : "my-room"
    logger.info(f"room metadata : '{ctx.job.metadata}'") # room metadata : 'hello from dispatch'

    # Determine if this is an outbound call from dispatch metadata  
    is_outbound = ctx.job.metadata == "outbound"  
    logger.info(f"Call type: {'OUTBOUND' if is_outbound else 'INBOUND'}")  

    ctx.log_context_fields = {
        "room": ctx.room.name,
    }
    # Set up a voice AI pipeline using OpenAI, Cartesia, Deepgram, and the LiveKit turn detector
    session = AgentSession(
        stt=deepgram.STT(language="fr",model="nova-3"),  # Use `language="fr-FR"` for French
        llm=openai.LLM(model="gpt-4.1-mini-2025-04-14"),
        tts=cartesia.TTS(voice="65b25c5d-ff07-4687-a04c-da2f43ef6fa9",model="sonic-2",language="fr"),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
        userdata = userdata
    )

    @session.on("close")
    def on_close(ev: CloseEvent):

        logger.info(f"Type of disconnection: {ev.reason}")
        logger.info(f"Agent disconnect reason {ctx.agent.disconnect_reason}")

        started_at = ctx.room.creation_time.astimezone(tz=ZoneInfo("Europe/Paris"))
        ended_at = datetime.fromtimestamp(ev.created_at, tz=ZoneInfo("Europe/Paris"))

        # Calculate duration
        duration = ended_at - started_at
        duration_seconds = duration.total_seconds()

        # Metadata
        metadata.disconnection_reason = ev.reason.name
        metadata.created_at = started_at.isoformat()
        metadata.ended_at = ended_at.isoformat()
        metadata.duration_seconds = duration_seconds

        logger.info(f"Metadata dict: {asdict(metadata)}")

        # Send data to backend APi asynchronously        
        async def post_data():
            async with aiohttp.ClientSession() as session:
                
                async with session.post("http://0.0.0.0:8000/calls/call", json=asdict(metadata)) as response:
                    return await response.json()
                
        # If you need the result, use ensure_future with callback
        task = asyncio.create_task(post_data())
        task.add_done_callback(lambda t: logger.info(f"Result from API: {t.result()}"))

    await session.start(
            agent=Assistant(),
            room=ctx.room,
            room_input_options=RoomInputOptions(
                noise_cancellation=noise_cancellation.BVCTelephony(),
            ),
        )
        
    # Handler for participant connection  
    def on_participant_connected_handler(participant: rtc.RemoteParticipant):  
        asyncio.create_task(async_on_participant_connected(participant))  
    
    # Handler for attribute changes (call status)  
    def on_participant_attributes_changed_handler(changed_attributes: dict, participant: rtc.Participant):  
        asyncio.create_task(async_on_participant_attributes_changed(changed_attributes, participant))  
    
    async def async_on_participant_connected(participant: rtc.RemoteParticipant):  
        logger.info(f"Participant connected: {participant.identity}")
        
        # Check if this is a SIP participant  
        if participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP:  
            logger.info(f"SIP participant connected: {participant.identity}")  
            
            # Log initial SIP attributes  
            if participant.attributes:  
                call_status = participant.attributes.get('sip.callStatus', 'Unknown')  
                phone_number = participant.attributes.get('sip.phoneNumber', 'Unknown') 
                trunk_phone = participant.attributes.get('sip.trunkPhoneNumber', 'Unknown')  
                call_id = participant.attributes.get('sip.callID', 'Unknown')  

                logger.info(f"Initial call status: {call_status}")  
                logger.info(f"Call ID: {call_id}")  
                logger.info(f"Phone number: {phone_number}")
                logger.info(f"Trunk phone: {trunk_phone}")

                # Use dispatch metadata to determine direction  
                if is_outbound:  
                    logger.info(f"📞 OUTBOUND CALL: FROM {trunk_phone} TO {phone_number}")    
                    metadata.to_number = phone_number  
                    metadata.from_number = trunk_phone
                    metadata.call_type = "outbound"
                else:  
                    logger.info(f"📞 INBOUND CALL: FROM {phone_number} TO {trunk_phone}")    
                    metadata.to_number = trunk_phone  
                    metadata.from_number = phone_number
                    metadata.call_type = "inbound"
                  
                # Store call_id  
                metadata.call_id = call_id



    async def async_on_participant_attributes_changed(changed_attributes: dict, participant: rtc.Participant):  
            logger.info(f"Participant {participant.identity} attributes changed: {changed_attributes}")  

            # Check if this is a SIP participant and if call status has changed  
            if participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP:  
                logger.info(f"Participant kind: {rtc.ParticipantKind.PARTICIPANT_KIND_SIP}")
                
                if 'sip.callStatus' in changed_attributes:  
                    call_status = changed_attributes['sip.callStatus']  
                    logger.info(f"SIP Call Status updated: {call_status}")  
                    
                    # Handle different call statuses  
                    if call_status == 'ringing':  
                        logger.info("Inbound call is ringing for the caller")  
                    elif call_status == 'active':  
                        logger.info("Call is now active and connected")  
                    elif call_status == 'dialing':  
                        logger.info("Call is dialing and waiting to be picked up")  
                    elif call_status == 'automation':  
                        logger.info("Call is connected and dialing DTMF numbers")  
                    elif call_status == 'hangup':  
                        logger.info("Call has been ended by a participant")  
        
    # Register both event handlers  
    ctx.room.on("participant_connected", on_participant_connected_handler)  
    ctx.room.on("participant_attributes_changed", on_participant_attributes_changed_handler)


    await ctx.connect()
    # Handle participants that joined before handlers were registered  
    for participant in ctx.room.remote_participants.values():  
        asyncio.create_task(async_on_participant_connected(participant))  

    participant = await ctx.wait_for_participant()


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint,
                              agent_name="my-telephony-agent",
                              prewarm_fnc=prewarm,
                              initialize_process_timeout=60,
                              #num_idle_processes=3,
                            ))
    