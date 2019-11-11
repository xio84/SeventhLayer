from websocket_server import *

SIZE_LIMIT = 125

# Called for every client connecting (after handshake)
def new_client(client, server):
	print("New client, id:" + str(client['id']))
	# server.send_message_to_all("Hey all, a new client has joined us")


# Client disconnection warning
def client_left(client, server):
	print("Client(" + str(client['id']) + ") disconnected")


# Message handler
def message_handler(client, server, message, fin):
	message = message.decode('utf-8')
	if (fin):
		if (' ' in message):
			(command, content) = message.split(' ', 1)
			(command, content) = (command.strip(), content.strip())
			if (command == '!echo'):
				server.send_message(client, content)
			if (command == '!submission'):
				file_request = 'upload/submission.zip'
				f = open(file_request, 'rb')
				packet_data = bytearray(f.read(SIZE_LIMIT))
				# if (len(packet_data) <= 125):
				# 	pass
			if (command == '!check'):
				pass
	else:
		server.message_buffer += message
		server.message_or_binary = 0

# Binary handler
def binary_handler(client, server, message, fin):
	pass

PORT=9001
server = WebsocketServer(PORT)
server.set_new_client_handler(new_client)
server.set_client_left_handler(client_left)
server.set_message_received_handler(message_handler)
# server.set_binary_received_handler()
# server.set_continuation_received_handler()
server.run_forever()
