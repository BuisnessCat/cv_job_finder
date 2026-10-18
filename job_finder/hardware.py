"""The graphics card's memory and the model that fits it (spec section 18.4)."""
from job_finder import config

# Display adapters in the registry: each has its memory size, also for AMD and Intel cards
ADAPTERS_KEY = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
SMALL_CARD_GB = 7.5  # an 8 GB card reports a bit less than 8


def _registry_sizes() -> list:
    """The raw memory size values of all display adapters (bytes or a number); Windows only."""
    import winreg
    sizes = []
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, ADAPTERS_KEY) as adapters:
        index = 0
        while True:
            try:
                name = winreg.EnumKey(adapters, index)
            except OSError:
                return sizes
            index += 1
            try:
                with winreg.OpenKey(adapters, name) as adapter:
                    sizes.append(winreg.QueryValueEx(adapter, "HardwareInformation.qwMemorySize")[0])
            except OSError:
                continue  # "Properties" and adapters without the value


def vram_gb(read=_registry_sizes) -> float | None:
    """The memory of the biggest graphics card in GB, or None if it can't be told."""
    try:
        values = read()
    except (OSError, ImportError):
        return None
    sizes = [int.from_bytes(value, "little") if isinstance(value, bytes) else value
             for value in values if isinstance(value, (bytes, int))]
    sizes = [size for size in sizes if size > 0]
    return round(max(sizes) / 2 ** 30, 1) if sizes else None


def model_for_vram(gb: float | None) -> str:
    return config.SMALL_MODEL if gb is not None and gb < SMALL_CARD_GB else config.MODEL


_default = None


def default_model() -> str:
    """The model for this computer's graphics card (read once)."""
    global _default
    if _default is None:
        _default = model_for_vram(vram_gb())
    return _default
