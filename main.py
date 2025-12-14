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
    AudioConfig,
    BackgroundAudioPlayer,
    BuiltinAudioClip
    
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
from inbound_agent import InboundAssistant
from outbound_agent import OutboundAssistant
from classes import UserData, MetaData
from utils import post_data

logger = logging.getLogger("main")

load_dotenv("/home/raymond/Projects/LeadOutbountCaller/.env.local")
outbound_trunk_id = os.getenv("SIP_OUTBOUND_TRUNK_ID")



def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()

async def entrypoint(ctx: JobContext):

    userdata = UserData()
    metadata = MetaData()
    
    logger.info(f"connecting to room '{ctx.room.name}'") # room : "my-room"
    userdata.room_name = ctx.room.name
    logger.info(f"room metadata : '{ctx.job.metadata}'") # Room from dispatch metadata : 'hello from dispatch'

    # Convert text to json
    if ctx.job.metadata:
        metadata = json.loads(ctx.job.metadata)

        # Determine if this is an outbound call from dispatch metadata  
        call_type = metadata.get("call_type")
        data = metadata.get("data")
        
        logger.info(f"Call type: {call_type}")   # Type dict
        logger.info(f"data sent from backend: {data}")
    
    call_type = "inbound"

    # Change instruction based on call type
    ctx.log_context_fields = {"room": ctx.room.name}

    session = AgentSession(
        stt=deepgram.STT(language="fr",model="nova-3"),  # Use `language="fr-FR"` for French
        llm=openai.LLM(model="gpt-4.1-mini-2025-04-14"),
        tts=cartesia.TTS(
            voice="65b25c5d-ff07-4687-a04c-da2f43ef6fa9",
            model="sonic-2",
            language="fr"),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
        userdata = userdata
    )

    if call_type == "outbound":
        agent = OutboundAssistant(url_api="http://3.88.182.81:8000/calls/call",
                                 fname=data.get("first_name"),
                                 lname=data.get("last_name"),
                                 email=data.get("email"),
                                 phone_number=data.get("email")
                                 )
    elif call_type == "inbound":
        agent = InboundAssistant(call_type="inbound",url_api="http://3.88.182.81:8000/calls/call")
    else:
        logger.info(f"Check againg the call type: {call_type}")

    await session.start(
            agent=agent,
            room=ctx.room,
            room_input_options=RoomInputOptions(
                noise_cancellation=noise_cancellation.BVCTelephony(),
            ),
        )
    background_audio = BackgroundAudioPlayer(
        # play office ambience sound looping in the background
        ambient_sound=AudioConfig(BuiltinAudioClip.OFFICE_AMBIENCE, volume=0.8),
        # play keyboard typing sound when the agent is thinking
        thinking_sound=[
            AudioConfig(BuiltinAudioClip.KEYBOARD_TYPING, volume=0.8),
            AudioConfig(BuiltinAudioClip.KEYBOARD_TYPING2, volume=0.7),
        ],
    )

    await background_audio.start(room=ctx.room, agent_session=session)

        
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
                if call_type == "outbound":  
                    logger.info(f"📞 OUTBOUND CALL: FROM {trunk_phone} TO {phone_number}")    
                    userdata.to_number = phone_number  
                    userdata.from_number = trunk_phone
                    userdata.call_type = "outbound"
                else:  
                    logger.info(f"📞 INBOUND CALL: FROM {phone_number} TO {trunk_phone}")    
                    userdata.to_number = trunk_phone  
                    userdata.from_number = phone_number
                    userdata.call_type = "inbound"
                  
                # Store call_id  
                userdata.call_id = call_id

                # Start recording AFTER we have the call_id  
                # try:  
                #    async with api.LiveKitAPI() as lkapi:
                #        req = api.RoomCompositeEgressRequest(  
                #            room_name=ctx.room.name,  
                #            layout="speaker",  
                #            preset=api.EncodingOptionsPreset.H264_720P_30,  
                #            audio_only=True,  
                #            segment_outputs=[api.SegmentedFileOutput(  
                #                filename_prefix=f"call-{call_id}",  
                #                playlist_name="recording.m3u8",  
                #                segment_duration=5,
                #                s3=api.S3Upload(
                #                    access_key=os.getenv("AWS_ACCESS_KEY_ID"),
                #                    secret=os.getenv("AWS_SECRET_ACCESS_KEY"),
                #                    region=os.getenv("AWS_REGION"),
                #                    bucket=os.getenv("S3_BUCKET_NAME"),)
                #
                #            )],  
                #        )  
                #        egress_info = await lkapi.egress.start_room_composite_egress(req)  
                #        logger.info(f"Egresse info: {egress_info}")
                #        logger.info(f"Recording started: {egress_info.egress_id}")  
                #except Exception as e:  
                #    logger.error(f"Failed to start recording: {e}")  



    async def async_on_participant_attributes_changed(changed_attributes: dict, participant: rtc.Participant):  
            logger.info(f"Participant {participant.identity} attributes changed: {changed_attributes}")  

            # Check if this is a SIP participant and if call status has changed  
            if participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP:  
                logger.info(f"Participant kind: {rtc.ParticipantKind.PARTICIPANT_KIND_SIP}")
                
                if 'sip.callStatus' in changed_attributes:  
                    call_status = changed_attributes['sip.callStatus']  
                    logger.info(f"SIP Call Status updated: {call_status}")  
                    
                    if call_status == 'active':  
                        logger.info("Call is now active and connected")  
                    elif call_status == 'hangup':
                        userdata.disconnection_reason = "HANGUP_BY_CALLEE"
                        logger.info("Call has been ended by a participant")
            
            if participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_AGENT:  
                logger.info(f"Participant kind: {rtc.ParticipantKind.PARTICIPANT_KIND_AGENT}")
                attributes = participant.attributes  
                logger.info(f"Agent participant attributes: {attributes}")

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
    