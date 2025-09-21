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
    get_job_context,
    ChatContext
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
OPENAI_API_KEY = "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"

# Add this function definition anywhere
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
from livekit.agents import AgentTask, function_tool

class CollectConsent(AgentTask[bool]):
    def __init__(self, chat_ctx=None):
        super().__init__(
            instructions="""Your name is Jamie. You are a friendly helper that works with GreenSoler""",
            chat_ctx=chat_ctx,
        )

        message_to_add = self.chat_ctx.copy()
        self.update_chat_ctx(message_to_add)



    async def on_enter(self) -> None:
        logger.info(f"On enter 'CollectConsent' self. chat context : {self.chat_ctx.to_dict()}")

        await self.session.generate_reply(
            instructions="""
            Your name is Jamie, then ask if it is a good time for a quick 2-minutes call.
            Make it clear that they can decline.
            """
        )

    @function_tool
    async def consent_given(self) -> None:
        """Use this when the user gives yes as answer."""
        self.complete(True)

    @function_tool
    async def consent_denied(self) -> None:
        """Use this when the user gives no as answer."""
        self.complete(False)

    
class Assistant(Agent):
    def __init__(self):
        instuctions = """
        Your name is Jamie. You are a friendly helper that works with GreenSoler
        1. first question
        Do you currently own your home, or are you renting?
        """
        super().__init__(instructions="")

    async def on_enter(self) -> None:
        logger.info(f"On enter 'Assistant' chat context : {self.chat_ctx.items}")
        if await CollectConsent(chat_ctx=self.chat_ctx):
            await self.session.generate_reply(instructions="Thank the called person and tell him that you have quick question if their services are relevant for called.")

        else:
            await self.session.say(text="I understand, I won’t keep you. Would you like me to try again at a better time?")
    

    @function_tool
    async def call_later(self, ctx: RunContext):
        """Called when the user wants to be called again"""
        
    
    @function_tool
    async def end_call(self, ctx: RunContext):
        """Called when the user wants to end the call"""
        await ctx.wait_for_playout() # let the agent finish speaking
        await hangup_call()

            

async def entrypoint(ctx: JobContext):


    logger.info(f"connecting to room '{ctx.room.name}'") # room : "my-room"
    await ctx.connect()

    logger.info(f"room metadata : '{ctx.job.metadata}'") # room metadata : 'hello from dispatch'

    ctx.log_context_fields = {
        "room": ctx.room.name,
    }
    # Set up a voice AI pipeline using OpenAI, Cartesia, Deepgram, and the LiveKit turn detector
    session = AgentSession(
        llm=openai.LLM(model="gpt-4o-mini",api_key=OPENAI_API_KEY),
        stt=openai.STT(api_key=OPENAI_API_KEY),
        tts=openai.TTS(api_key=OPENAI_API_KEY),
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
    