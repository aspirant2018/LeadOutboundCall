import logging

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
)
from livekit import rtc, api
from livekit.agents.llm import function_tool
from livekit.plugins import cartesia, deepgram, noise_cancellation, openai, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel
import os

import asyncio
logger = logging.getLogger("main")

load_dotenv(".env.local")
def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()

outbound_trunk_id = os.getenv("SIP_OUTBOUND_TRUNK_ID")


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions="""You are a helpful voice AI assistant.
            You eagerly assist users with their questions by providing information from your extensive knowledge.
            Your responses are concise, to the point, and without any complex formatting or punctuation including emojis, asterisks, or other symbols.
            You are curious, friendly, and have a sense of humor.""",
        )


async def entrypoint(ctx: JobContext):



    logger.info(f"connecting to room '{ctx.room.name}'") # room : "my-room"
    await ctx.connect()

    logger.info(f"room metadata : '{ctx.job.metadata}'") # room metadata : 'hello from dispatch'

    ctx.log_context_fields = {
        "room": ctx.room.name,
    }
    # Set up a voice AI pipeline using OpenAI, Cartesia, Deepgram, and the LiveKit turn detector
    session = AgentSession(
        llm=openai.LLM(model="gpt-4o-mini"),
        stt=openai.STT(),
        tts=openai.TTS(),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
    )
    
    # Start the session, which initializes the voice pipeline and warms up the models
    # start the session first before dialing, to ensure that when the user picks up
    # the agent does not miss anything the user says
    session_started = asyncio.create_task(
        session.start(
            agent=Assistant(),
            room=ctx.room,
            room_input_options=RoomInputOptions(
                # enable Krisp background voice and noise removal
                noise_cancellation=noise_cancellation.BVCTelephony(),
            ),
        )
    )

    phone_number = "+33758611523"

    try:
        await ctx.api.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                room_name=ctx.room.name,
                sip_trunk_id="ST_HmABTkLetTjG",
                sip_call_to=phone_number,
                participant_identity=f'sip_{phone_number}',
                # function blocks until user answers the call, or if the call fails
                wait_until_answered=True,
            )
        )
        # wait for the agent session start and participant join
        await session_started
        participant = await ctx.wait_for_participant(identity=f'sip_+33758611523')
        logger.info(f"participant joined: {participant.identity}")

    except api.TwirpError as e:
        logger.error(
            f"error creating SIP participant: {e.message}, "
            f"SIP status: {e.metadata.get('sip_status_code')} "
            f"{e.metadata.get('sip_status')}"
        )
        ctx.shutdown()




if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint,
                              agent_name="my-telephony-agent",
                              prewarm_fnc=prewarm,
                              initialize_process_timeout=60
                            ))
    