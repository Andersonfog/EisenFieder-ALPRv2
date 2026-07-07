"""EisenFieder Surveillance edge package — entrance camera software.

Mock-first: every AI stage (vehicle detection, plate reading, attribute
recognition) ships with a dependency-free *mock* backend so the whole
capture -> recognize -> log -> upload pipeline runs on a laptop with nothing
installed but `requests` + `pyyaml`. The real models drop into the same
interfaces on the Raspberry Pi (+ Hailo).
"""

__version__ = "0.1.0"
