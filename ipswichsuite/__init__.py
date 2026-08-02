"""
IpswichSuite - DMR network server for FCC Part 90 and amateur systems
by Ipswich River Labs, LLC

IpswichSuite is a GPLv3 fork of HBlink4 by Cortney T. Buffington, N0MJS
(itself a redesign of HBlink3), extended for closed commercial (Part 90)
operation: subscriber/fleet access control, call detail records, and
fleet-oriented management. The HomeBrew DMR protocol is UDP-based, used
for communication between DMR repeaters and servers.

Copyright (C) 2016-2025 Cortney T. Buffington, N0MJS (HBlink3/HBlink4)
Copyright (C) 2025-2026 Ipswich River Labs, LLC (IpswichSuite additions)
License: GNU GPLv3
"""

from .server import main, HBProtocol, RepeaterState
from .constants import *
from .constants import PRODUCT_NAME, PRODUCT_VENDOR

__version__ = '1.0.0'
__author__ = 'Ipswich River Labs, LLC'
__license__ = 'GNU GPLv3'

__all__ = [
    'main',
    'HBProtocol',
    'RepeaterState',
    'PRODUCT_NAME',
    'PRODUCT_VENDOR'
]
