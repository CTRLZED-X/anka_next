"""Offline-only window/calibration compatibility; NEVER approves game input."""
from __future__ import annotations
from anka_contracts.client import WindowObservation


def geometry_diagnosis(window: WindowObservation, reference: tuple[int,int] = (1280,649)) -> dict:
    notes=[]
    size=(window.client_width,window.client_height)
    if size!=reference:notes.append('WINDOW_SIZE_DIFFERS_FROM_HISTORICAL_CALIBRATION')
    if window.dpi is None:notes.append('WINDOW_DPI_UNKNOWN')
    if window.minimized:notes.append('WINDOW_MINIMIZED')
    # Exact size/DPI alone are NOT sufficient to prove pixel-space equivalence.
    notes.extend(('CLIENT_COORDINATE_SPACE_UNCERTIFIED','CURRENT_BUILD_SPELL_SLOTS_UNCERTIFIED'))
    return {'observed_size':list(size), 'historical_reference_size':list(reference),
            'observed_dpi':window.dpi, 'observationally_matching_size':size==reference,
            'live_calibration_certified':False, 'issues':notes}
