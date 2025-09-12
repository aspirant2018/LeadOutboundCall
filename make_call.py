import asyncio
import os
import logging
from pathlib import Path
from dotenv import load_dotenv
from livekit import api



load_dotenv(".env.local")

print(f"the loaded env is\n{Path('.env.local').read_text()}")
# Configuration
room_name = "my-room"
agent_name = "my-telephony-agent"
outbound_trunk_id = os.getenv("SIP_OUTBOUND_TRUNK_ID")

async def main():
    # Replace with the actual phone number including country code
    #phone_number = "+33758611523"
    
    """Create a dispatch and add a SIP participant to call the phone number"""
    lkapi = api.LiveKitAPI(
        url=os.getenv("LIVEKIT_URL"),
        api_key=os.getenv("LIVEKIT_API_KEY"),
        api_secret=os.getenv("LIVEKIT_API_SECRET"),
    )

    # Create agent dispatch
    print(f"Creating dispatch for agent : {agent_name} in room: {room_name}")
    dispatch = await lkapi.agent_dispatch.create_dispatch(
        api.CreateAgentDispatchRequest(
            agent_name=agent_name,
            room=room_name,
            metadata="hello from dispatch"
        )
    )
    print(f"Created dispatch: {dispatch}")
    
    # Create SIP participant to make the call
    if not outbound_trunk_id or not outbound_trunk_id.startswith("ST_"):
        print("SIP_OUTBOUND_TRUNK_ID is not set or invalid")
        return
    
    #print(f"Dialing {phone_number} to room {room_name}")
    
    #try:
        # Create SIP participant to initiate the call
    #    sip_participant = await lkapi.sip.create_sip_participant(
    #        api.CreateSIPParticipantRequest(
    #            room_name=room_name,
    #            sip_trunk_id=outbound_trunk_id,
    #            sip_call_to=phone_number,
    #            participant_identity=f'sip_{phone_number}',
    #            participant_name="SIP Caller",
    #        )
    #    )

        # sip_trunk_id=sip_trunk_id,
        # sip_call_to=phone_number,
        # room_name=room_name,
        #        participant_identity=f"sip_{phone_number}",
        #        participant_name="SIP Caller"
    #    print(f"Created SIP participant: {sip_participant}")
    #except Exception as e:
    #    print(f"Error creating SIP participant: {e}")
    
    # Close API connection
    await lkapi.aclose()

if __name__ == "__main__":
    
    asyncio.run(main())