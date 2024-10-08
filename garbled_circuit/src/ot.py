import hashlib
import logging
import pickle
import util
import yao


class ObliviousTransfer:
    def __init__(self, socket, enabled=True, group=None):
        self.socket = socket
        self.enabled = enabled
        self.group = group

    def get_result(self, a_inputs, b_keys):
        logging.debug("Sending inputs to Bob")
        self.socket.send_wait(a_inputs)

        logging.debug("Generating prime group to use for OT")
        self.group = self.enabled and (self.group or util.PrimeGroup())
        logging.debug("Sending prime group")
        self.socket.send(self.group)

        for _ in range(len(b_keys)):
            w = self.socket.receive()  # receive gate ID where to perform OT
            logging.debug(f"Received gate ID {w}")

            if self.enabled:  # perform oblivious transfer
                pair = (pickle.dumps(b_keys[w][0]), pickle.dumps(b_keys[w][1]))
                self.ot_garbler(pair)
            else:
                to_send = (b_keys[w][0], b_keys[w][1])
                self.socket.send(to_send)

        return self.socket.receive()

    def send_result(self, circuit, g_tables, pbits_out, b_inputs):
        # map from Alice's wires to (key, encr_bit) inputs
        a_inputs = self.socket.receive()
        self.socket.send(True)
        # map from Bob's wires to (key, encr_bit) inputs
        b_inputs_encr = {}

        logging.debug("Received Alice's inputs")

        self.group = self.socket.receive()
        logging.debug("Received group to use for OT")

        for w, b_input in b_inputs.items():
            logging.debug(f"Sending gate ID {w}")
            self.socket.send(w)

            if self.enabled:
                b_inputs_encr[w] = pickle.loads(self.ot_evaluator(b_input))
            else:
                pair = self.socket.receive()
                logging.debug(f"Received key pair, key {b_input} selected")
                b_inputs_encr[w] = pair[b_input]

        result = yao.evaluate(circuit, g_tables, pbits_out, a_inputs,
                              b_inputs_encr)

        logging.debug("Sending circuit evaluation")
        self.socket.send(result)
        return result

    def ot_garbler(self, msgs):
        logging.debug("OT protocol started")
        G = self.group

        c = G.gen_pow(G.rand_int())
        h0 = self.socket.send_wait(c)
        h1 = G.mul(c, G.inv(h0))
        k = G.rand_int()
        c1 = G.gen_pow(k)
        e0 = util.xor_bytes(msgs[0], self.ot_hash(G.pow(h0, k), len(msgs[0])))
        e1 = util.xor_bytes(msgs[1], self.ot_hash(G.pow(h1, k), len(msgs[1])))

        self.socket.send((c1, e0, e1))
        logging.debug("OT protocol ended")

    def ot_evaluator(self, b):
        logging.debug("OT protocol started")
        G = self.group

        c = self.socket.receive()
        x = G.rand_int()
        x_pow = G.gen_pow(x)
        h = (x_pow, G.mul(c, G.inv(x_pow)))
        c1, e0, e1 = self.socket.send_wait(h[b])
        e = (e0, e1)
        ot_hash = self.ot_hash(G.pow(c1, x), len(e[b]))
        mb = util.xor_bytes(e[b], ot_hash)

        logging.debug("OT protocol ended")
        return mb

    @staticmethod
    def ot_hash(pub_key, msg_length):
        """Hash function for OT keys."""
        key_length = (pub_key.bit_length() + 7) // 8  # key length in bytes
        bytes = pub_key.to_bytes(key_length, byteorder="big")
        return hashlib.shake_256(bytes).digest(msg_length)
