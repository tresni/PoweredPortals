# pylint: disable=unused-wildcard-import, wildcard-import
#
# This file is part of FaceDancer.
#

import asyncio

from facedancer.future import *
from facedancer.classes import *
from facedancer.classes.hid.usage import *
from facedancer.classes.hid.descriptor import *

from pathlib import Path
import os.path

import logging
import struct
import configparser

import skylander

portal_status = 0x00000000
LOG_FORMAT_COLOR = "\u001b[37;1m%(levelname)-8s| \u001b[0m\u001b[1m%(module)-15s|\u001b[0m %(message)s"
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


@use_inner_classes_automatically
class TestHIDDevice(USBDevice):
    device_class: int = 0
    device_subclass: int = 0
    protocol_revision_number: int = 0

    max_packet_size_ep0: int = 32

    vendor_id: int = 0x1430
    product_id: int = 0x0150

    manufacturer_string: str = "Activision"
    product_string: str = "Spyro Porta"
    serial_number_string: str = None

    active = False

    class Configuration(USBConfiguration):
        self_powered: bool = False
        supports_remote_wakeup: bool = False
        max_power: int = 300

        class Interface(USBInterface):
            class_number: int = USBDeviceClass.HID

            class InEndpoint(USBEndpoint):
                number: int = 1
                direction: USBDirection = USBDirection.IN
                transfer_type: USBTransferType = USBTransferType.INTERRUPT
                interval: int = 1
                max_packet_size: int = 32

                index = 0

                def handle_data_requested(self):
                    # This should probably  be done more like a keyboard example
                    # Would likely  simplify some of the tracking of portal_status
                    # But it  works (at least on the original game on Wii)
                    device = self.parent.parent.parent
                    resp = struct.pack('<sIBb', b'S', portal_status, self.index, device.active).ljust(0x20, b'\0')
                    self.send(resp)
                    self.index += 1
                    self.index %= 0xff

            class OutEndpoint(USBEndpoint):
                number: int = 1
                direction: USBDirection = USBDirection.OUT
                transfer_type: USBTransferType = USBTransferType.INTERRUPT
                interval: int = 1
                max_packet_size: int = 32

                def handle_data_received(self, data):
                    # Nothing seems to get here...
                    logger.info("Data recieved on OUT %s" % data)

            class ClassDescriptor(USBClassDescriptor):
                number: int = USBDescriptorTypeNumber.HID
                raw: bytes = b'\x09\x21\x11\x01\x00\x01\x22\x1d\x00'

            class ReportDescriptor(HIDReportDescriptor):
                fields: tuple = (
                    USAGE_PAGE(0x00, 0xff),
                    USAGE(0x01),
                    COLLECTION(HIDCollection.APPLICATION),
                    USAGE_MINIMUM(0x01),
                    USAGE_MAXIMUM(0x40),
                    LOGICAL_MINIMUM(0),
                    LOGICAL_MAXIMUM(0xff, 0x00),
                    REPORT_SIZE(0x08),
                    REPORT_COUNT(0x20),
                    INPUT(),
                    USAGE_MINIMUM(0x01),
                    USAGE_MAXIMUM(0x40),
                    OUTPUT(),
                    END_COLLECTION()
                )

            @class_request_handler(number=USBStandardRequests.GET_INTERFACE)
            @to_this_interface
            def handle_get_interface_request(self, request):
                request.ack()

            @class_request_handler(number=USBStandardRequests.SET_INTERFACE)
            @to_this_interface
            def handle_set_interface_request(self, request):
                request.ack()

            @class_request_handler(number=USBStandardRequests.SET_CONFIGURATION)
            @to_this_interface
            def handle_set_configuration_request(self, request):
                resp = None
                if request.data[0] == ord('R'):
                    resp = struct.pack('>sI', b'R', 0x020a0302).ljust(0x20, b'\0')
                elif request.data[0] == ord('A'):
                    if request.data[1]:
                        request.device.active = True
                    else:
                        request.device.active = False
                    resp = struct.pack('>sbH', b'A', request.device.active, 0xff77).ljust(0x20, b'\0')
                elif request.data[0] == ord('C') or request.data[0] == ord('S'):
                    pass
                elif request.data[0] == ord('Q'):
                    # Starting actually send 0x20 + offset
                    # Ending send 0x10 + offset
                    # We start slots at 1
                    slot = request.data[1] % 0x10 + 1
                    logger.debug("Requesting block %d from slot %d" % (request.data[2], slot))
                    data = slots[slot].skylander.readBlock(request.data[2])
                    resp = struct.pack('>s2s16s', b'Q', request.data[1:3], data)
                elif request.data[0] == ord('W'):
                    slot = request.data[1] % 0x10 + 1
                    logger.debug("Saving block %d for slot %d" % (request.data[2], slot))
                    slots[slot].skylander.writeBlock(request.data[2], request.data[3:])
                    resp = struct.pack('>s2s', b'W', request.data[1:3]).ljust(0x20, b'\0')
                else:
                    logger.warning("Unknown command string %s" % request.data)
                    request.stall()
                    return
                if resp:
                    request.device.send(1, resp)
                request.ack()


async def watcher():
    global portal_status
    mtime = 0
    while True:
        conffile = Path("/home/pi/portal.conf")
        check = os.path.getmtime(conffile)
        if check > mtime:
            logger.info("Reloading portal.conf %d > %d" % (check, mtime))
            config = configparser.ConfigParser()
            config.read(conffile)
            for index in range(1, 16):
                path = config.get('slots', str(index), fallback=None)
                if slots[index].skylander and slots[index].skylander.path != path:
                    # This should set the most significant bit and remove the least significant bit
                    portal_status ^= 3 << 2 * (index - 1)
                    # Give it a second to get noticed
                    await asyncio.sleep(1)
                    # Remove most significant bit (nothing has changed)
                    portal_status ^= 1 << 2 * (index - 1) + 1
                    # Give it a second to get noticed
                    await asyncio.sleep(1)
                    logger.info("Saving skylander in slot %d: %s", index, slots[index].skylander.path)
                    slots[index].skylander.save()
                    slots[index].skylander = None
                if not slots[index].skylander and path:
                    slots[index].skylander = skylander.Skylander(path)
                    # Message that it is coming on
                    portal_status |= 3 << 2 * (index - 1)
                    await asyncio.sleep(1)
                    # Remove most significant bit to show it's still on the board
                    portal_status ^= 1 << 2 * (index - 1) + 1
                    # Give it a second to get noticed
                    await asyncio.sleep(1)

            mtime = check
        await asyncio.sleep(1)

slots = []
for _ in range(16):
    slots.append(skylander.Slot())

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT_COLOR)

    portal = TestHIDDevice()
    portal.emulate(watcher())
