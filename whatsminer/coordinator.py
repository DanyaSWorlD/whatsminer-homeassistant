import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

import async_timeout
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import (
    WhatsminerMachine,
    WhatsminerApi,
    Summary,
    PowerUnitDetails,
    Version,
    WhatsminerException,
    TokenError,
    DecodeError,
    MinerOffline,
    WhatsMinerApi20,
)
from .const import DOMAIN, CONF_HOST, CONF_PORT, CONF_PASSWORD, CONF_MAC

_LOGGER = logging.getLogger(__name__)


@dataclass
class MinerData(object):
    device_model: Optional[str]


@dataclass
class OnlineMinerData(MinerData):
    summary: Summary
    power_unit: PowerUnitDetails
    version: Version


class WhatsminerCoordinator(DataUpdateCoordinator[MinerData]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        super(WhatsminerCoordinator, self).__init__(
            hass,
            logging.getLogger(__name__),
            name=DOMAIN,
            update_method=self.async_fetch,
            update_interval=timedelta(seconds=5),
        )

        host = entry.data[CONF_HOST]
        port = entry.data[CONF_PORT]
        password = entry.data[CONF_PASSWORD]
        self.version = Version("empty", "empty")
        self.machine = WhatsminerMachine(host, port, password)
        self.api: WhatsminerApi = await self.detect_api()
        self.device_host: str = host
        self.device_model: Optional[str] = None
        self.device_mac: str = entry.data[CONF_MAC]

    async def async_fetch(self) -> MinerData:
        try:
            status = await self.api.get_status()

            if self.device_model is None:
                async with async_timeout.timeout(10):
                    details = await self.api.get_device_details()
                    self.device_model = details[0].model

            if not status.miner_online:
                raise MinerOffline()

            async with async_timeout.timeout(10):
                summary = await self.api.get_summary()

            async with async_timeout.timeout(10):
                psu = await self.api.get_psu()

            return OnlineMinerData(
                self.device_model, summary=summary, power_unit=psu, version=self.version
            )
        except (TokenError, DecodeError) as error:
            raise ConfigEntryAuthFailed from error
        except MinerOffline:
            return MinerData(self.device_model)
        except WhatsminerException as error:
            raise UpdateFailed from error
        except Exception as error:
            _LOGGER.warning("Unexpected error: %s", error)
            raise UpdateFailed from error

    async def detect_api(self):
        try:
            api = WhatsminerApi(self.machine)
            self.version = await api.get_version()
        except KeyError:
            api = WhatsMinerApi20(self.machine)
            self.version = await api.get_version()

        return api
