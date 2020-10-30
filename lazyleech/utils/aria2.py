import os
import json
import time
import base64
import random
import asyncio
import tempfile

HEX_CHARACTERS = 'abcdef'
HEXNUMERIC_CHARACTERS = HEX_CHARACTERS + '0123456789'

class Aria2Error(Exception):
    def __init__(self, message):
       self.error_code = message.get('code')
       self.error_message = message.get('message')
       return super().__init__(str(message))

def _raise_or_return(data):
    if 'error' in data:
        raise Aria2Error(data['error'])
    return data['result']

async def aria2_request(session, method, params=[]):
    data = {'jsonrpc': '2.0', 'id': str(time.time()), 'method': method, 'params': params}
    async with session.post('http://127.0.0.1:6800/jsonrpc', data=json.dumps(data)) as resp:
        return await resp.json(encoding='utf-8')

async def aria2_tell_active(session):
    return _raise_or_return(await aria2_request(session, 'aria2.tellActive'))

async def aria2_tell_status(session, gid):
    return _raise_or_return(await aria2_request(session, 'aria2.tellStatus', [gid]))

async def aria2_change_option(session, gid, options):
    return _raise_or_return(await aria2_request(session, 'aria2.changeOption', [gid, options]))

async def aria2_remove(session, gid):
    return _raise_or_return(await aria2_request(session, 'aria2.remove', [gid]))

async def generate_gid(session, user_id):
    def _generate_gid():
        gid = str(user_id)
        gid += random.choice(HEX_CHARACTERS)
        while len(gid) < 16:
            gid += random.choice(HEXNUMERIC_CHARACTERS)
        return gid
    while True:
        gid = _generate_gid()
        try:
            await aria2_tell_status(session, gid)
        except Aria2Error as ex:
            if not (ex.error_code == 1 and ex.error_message == f'GID {gid} is not found'):
                raise
            return gid

def is_gid_owner(user_id, gid):
    return gid.split(str(user_id), 1)[-1][0] in HEX_CHARACTERS

async def aria2_add_torrent(session, user_id, link, timeout=0):
    if os.path.isfile(link):
        with open(link, 'rb') as file:
            torrent = base64.b64encode(file.read()).decode()
    else:
        async with session.get(link) as resp:
            torrent = base64.b64encode(await resp.read()).decode()
    dir = os.path.join(
        os.getcwd(),
        str(user_id),
        str(time.time())
    )
    return _raise_or_return(await aria2_request(session, 'aria2.addTorrent', [torrent, [], {
        'gid': await generate_gid(session, user_id),
        'dir': dir,
        'seed-time': 0,
        'bt-stop-timeout': str(timeout)
    }]))

async def aria2_add_magnet(session, user_id, link, timeout=0):
    with tempfile.TemporaryDirectory() as tempdir:
        gid = _raise_or_return(await aria2_request(session, 'aria2.addUri', [[link], {
            'dir': tempdir,
            'bt-save-metadata': 'true',
            'bt-metadata-only': 'true',
            'follow-torrent': 'false'
        }]))
        try:
            info = await aria2_tell_status(session, gid)
            while info['status'] == 'active':
                await asyncio.sleep(0.5)
                info = await aria2_tell_status(session, gid)
            filename = os.path.join(tempdir, info['infoHash'] + '.torrent')
            return await aria2_add_torrent(session, user_id, filename, timeout)
        finally:
            try:
                await aria2_remove(session, gid)
            except Aria2Error as ex:
                if not (ex.error_code == 1 and ex.error_message == f'Active Download not found for GID#{gid}'):
                    raise
