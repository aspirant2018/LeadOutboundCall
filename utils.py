import aiohttp
from dataclasses import  asdict


# Send data to backend APi asynchronously        
async def post_data(url:str, metadata):
       async with aiohttp.ClientSession() as session:
              async with session.post(url, json=asdict(metadata)) as response:
                    return await response.json()


'''

import requests


def post_data(url, metadata):
    result = requests.post(url, json=asdict(metadata))
    return result 


    '''