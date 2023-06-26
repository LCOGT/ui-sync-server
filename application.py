import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, session, request
from flask_socketio import SocketIO, Namespace, emit, join_room, leave_room, \
    rooms, disconnect
from flask_cors import CORS
import json
from typing import Any
from pprint import pprint

# Set this variable to "threading", "eventlet" or "gevent" to test the
# different async modes, or leave it set to None for the application to choose
# the best option based on installed packages.
async_mode = 'eventlet'

application = app = Flask(__name__)
application.config['SECRET_KEY'] = 'secret!'
CORS(application, resources={r'/*': {'origins': '*'}})
socketio = SocketIO(application, cors_allowed_origins='*', async_mode=async_mode)

@app.route("/")
def online_status():
    return "<p>UI Sync is online</p>"

# Helper method to enable json conversion with sets
def set_default(obj):
    if isinstance(obj, set):
        return list(obj)
    raise TypeError

# State Management Below

followers = {}
site_states = {}
""""
example_state_storage = {
    "mrc1": {
        "state": {
            "command_params/mount_ra": 12.34,
            "command_params/mount_dec": 56.78,
            ...
        },
        "leader": {
            "admin": False,
            "name": "Tim Beccue",
            "id": "abcd1234"
            ...
        },
        "leader_sid": "session_id_1234",
    }, 
    "mrc2": {...}  
    ...
}
"""
        
# Helper methods below

def new_leader(user: dict, site: str, state_snapshot: dict, leader_sid: str):
    print('new leader')
    # Save the state dump in the server
    site_states[site] = {
        "state": state_snapshot,
        "leader": user,
        "leader_sid": leader_sid
    }

    # Notify followers at the site of a new leader, and send the full state to sync
    full_state_payload = {
        "state_snapshot": site_states[site]["state"],
        "leader": site_states[site]["leader"]
    }
    emit('full_state_snapshot', full_state_payload, room=site)

    # Confirm start of session with leader
    emit('confirm_leader_start', { "site": site })
    update_client_leader_list()

def new_follower(site: str):
    # Join the room
    join_room(site)

    followers[request.sid] = site

    if site in site_states:
        # Send a full state snapshot for the follower to sync
        full_state_payload = {
            "state_snapshot": site_states[site]["state"],
            "leader": site_states[site]["leader"]
        }
        emit('full_state_snapshot', full_state_payload)

    print('followers: ', followers)
    
    # Confirm start of session with follower
    emit('confirm_follower_start', { "site": site })

def remove_follower(site: str):
    leave_room(site)
    followers.pop(request.sid)
    print('followers: ', followers)
    # Confirm with user that they stopped following
    emit('confirm_follower_end', { "site": site })

def remove_leader(site: str):
    old_leader_state = site_states.pop(site)
    response_payload = {
        "site": site,
        "leader_name": old_leader_state["leader"]["name"]
    }

    # Confirm end of session to the leader
    emit('confirm_leader_end', { "site": site })

    # Notify followers of the end of the leader's session
    emit('no_more_leader', response_payload, room=site)
    update_client_leader_list()

def get_site_leaders() -> dict: 
    return { site: site_states[site]["leader"]["name"] for site in site_states }

def update_client_leader_list():
    payload = { "leaders": get_site_leaders() }
    emit("all_leaders", payload, broadcast=True, include_self=False)

# Get the dict where key=leader_sid and val=site
# Used to check whether a disconnect happened from a leader
def check_and_handle_leader_disconnect(state_storage, leader_sid): 
    for site in state_storage:
        if leader_sid == state_storage[site]["leader_sid"]:
            remove_leader(site)

def handle_new_state_change(site: str, key: str, val: Any): 
    # Modify server state
    try:
        site_states[site]["state"][key] = val
    except Exception as e:
        print(e)
        pprint(site_states)
    # Send to followers
    outbound_payload = {
        "key": key,
        "new_val": val 
    }
    emit("new_state", outbound_payload, room=site)


# Websocket Handlers Below
@socketio.on('ui_change')
def handle_ui_change(payload):
    print(payload)
    site = payload['site']
    mutation_name = payload['mutation_name']
    val = payload['new_val']
    handle_new_state_change(site, mutation_name, val)

@socketio.on('new_leader')
def handle_new_leader(payload):
    payload = json.loads(payload)
    print('new leader for ', payload['site'])
    user = payload['leader']
    site = payload['site']
    state_snapshot = payload['full_state_snapshot']
    new_leader(user, site, state_snapshot, request.sid)

@socketio.on('remove_leader')
def handle_remove_leader(payload):
    site = payload['site']
    print('removing leader gracefully at ', site)
    remove_leader(site)

@socketio.on('join_room')
def handle_join_room(payload):
    print('new follower at ', payload['site'])
    site = payload['site']
    new_follower(site)

@socketio.on('leave_room')
def handle_leave_room(payload):
    site = payload['site']
    print('removing follower at ', site)
    remove_follower(site)

@socketio.on('connect')
def handle_connect():
    connection_response = { "leaders": get_site_leaders() }
    emit('confirm_connect', connection_response)

@socketio.on('disconnect')
def handle_disconnect():
    check_and_handle_leader_disconnect(site_states, request.sid)
    print('Client disconnected', request.sid)

@socketio.on('my_ping')
def handle_my_ping():
    emit('my_pong')

#if __name__ == '__main__':
    #socketio.run(app, host="0.0.0.0", port="8000")
    #socketio.run(application)
