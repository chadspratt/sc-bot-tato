from typing import List

from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

# from sc2.ids.upgrade_id import UpgradeId


class BuildStarts():
    @staticmethod
    def get_build_start(build_name: str) -> List[UnitTypeId | UpgradeId]:
        if build_name == "empty":
            return []
        elif build_name == "test":
            return [
                # UnitTypeId.THOR,
                # UnitTypeId.BARRACKS,
                # UnitTypeId.REFINERY,
                # UnitTypeId.BARRACKSTECHLAB,
                # UpgradeId.SHIELDWALL
            ]
        elif build_name == "pig_b2gm":
            return [
                UnitTypeId.SCV,
                UnitTypeId.SCV,
                UnitTypeId.SUPPLYDEPOT,                 # wall at ramp or main edge,
                # UnitTypeId.SCV,
                # UnitTypeId.SCV,
                UnitTypeId.REFINERY,
                UnitTypeId.BARRACKS,
                # UnitTypeId.SCV,
                # UnitTypeId.SCV,
                # UnitTypeId.SCV,
                UnitTypeId.REFINERY,                    # 2ND GAS,
                UnitTypeId.REAPER,
                UnitTypeId.MARINE,
                # UnitTypeId.ORBITALCOMMAND,              # MAIN,
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.COMMANDCENTER,               # NATURAL, on location if safe, pause SCVs to pay for this
                UnitTypeId.FACTORY, # XXX after reactor if getting cheesed
                UnitTypeId.BARRACKSREACTOR, # XXX before factory if getting cheesed
                UnitTypeId.MARINE,
                UnitTypeId.MARINE,
                UnitTypeId.BUNKER,                      # NATURAL choke, XXX on high ground if getting cheesed
                UnitTypeId.FACTORYTECHLAB,              # fast SIEGETANK access,
                UnitTypeId.STARPORT,
                UnitTypeId.SIEGETANK,                   # start as soon as TECHLAB is ready,
                UnitTypeId.MARINE,               # begin reactor cycles,
                UnitTypeId.MARINE,
# from here, keep SCV and MULE production constant until ~45 workers (author logic)
                UnitTypeId.MARINE,
                UnitTypeId.MARINE,
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.MEDIVAC, # early medivac good?
                UnitTypeId.MARINE,
                UnitTypeId.MARINE,
                # UnitTypeId.SIEGETANK,
                UnitTypeId.BARRACKS,
                UnitTypeId.MARINE, # supply blocked until depot finishes
                UnitTypeId.MARINE,
                UnitTypeId.REFINERY,
                UnitTypeId.MARINE,
                UnitTypeId.MARINE,
                UnitTypeId.VIKINGFIGHTER,               # safer baseline scout vs all races (LIBERATOR optional),
            ]
        elif build_name == "pig_b2gm protoss":
            return [
                UnitTypeId.SCV,
                UnitTypeId.SCV,
                UnitTypeId.SUPPLYDEPOT,                 # wall at ramp or main edge,
                UnitTypeId.REFINERY,
                UnitTypeId.BARRACKS,
                UnitTypeId.REFINERY,                    # 2ND GAS,
                UnitTypeId.REAPER,
                UnitTypeId.MARINE,
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.COMMANDCENTER,               # NATURAL, on location if safe, pause SCVs to pay for this
                UnitTypeId.FACTORY, # XXX after reactor if getting cheesed
                UnitTypeId.BARRACKSREACTOR, # XXX before factory if getting cheesed
                UnitTypeId.MARINE,
                UnitTypeId.MARINE,
                UnitTypeId.BUNKER,                      # NATURAL choke, XXX on high ground if getting cheesed
                UnitTypeId.FACTORYTECHLAB,              # fast SIEGETANK access,
                UnitTypeId.STARPORT,
                UnitTypeId.SIEGETANK,                   # start as soon as TECHLAB is ready,
                UnitTypeId.MARINE,               # begin reactor cycles,
                UnitTypeId.MARINE,
                UnitTypeId.STARPORTTECHLAB,
                UnitTypeId.BANSHEE,
                UpgradeId.BANSHEECLOAK,
                UnitTypeId.BANSHEE,
                UnitTypeId.MARINE,
                UnitTypeId.MARINE,
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.MARINE,
                UnitTypeId.MARINE,
                UnitTypeId.MEDIVAC, # early medivac good?
                UnitTypeId.BARRACKS,
                UnitTypeId.MARINE, # supply blocked until depot finishes
                UnitTypeId.MARINE,
                UnitTypeId.REFINERY,
                UnitTypeId.MARINE,
                UnitTypeId.MARINE,
                UnitTypeId.VIKINGFIGHTER, 
            ]
        elif build_name == "pig_b2gm zerg":
            return [
                UnitTypeId.SCV,
                UnitTypeId.SCV,
                UnitTypeId.SUPPLYDEPOT,                 # wall at ramp or main edge,
                # UnitTypeId.SCV,
                # UnitTypeId.SCV,
                UnitTypeId.REFINERY,
                UnitTypeId.BARRACKS,
                # UnitTypeId.SCV,
                # UnitTypeId.SCV,
                # UnitTypeId.SCV,
                UnitTypeId.REFINERY,                    # 2ND GAS,
                UnitTypeId.REAPER,
                UnitTypeId.MARINE,
                # UnitTypeId.ORBITALCOMMAND,              # MAIN,
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.COMMANDCENTER,               # NATURAL, on location if safe, pause SCVs to pay for this
                UnitTypeId.FACTORY, # XXX after reactor if getting cheesed
                UnitTypeId.BARRACKSREACTOR, # XXX before factory if getting cheesed
                UnitTypeId.MARINE,
                UnitTypeId.MARINE,
                UnitTypeId.BUNKER,                      # NATURAL choke, XXX on high ground if getting cheesed
                UnitTypeId.FACTORYTECHLAB,              # fast SIEGETANK access,
                UnitTypeId.STARPORT,
                UnitTypeId.SIEGETANK,                   # start as soon as TECHLAB is ready,
                UnitTypeId.MARINE,               # begin reactor cycles,
                UnitTypeId.MARINE,
                UnitTypeId.STARPORTTECHLAB,
                UnitTypeId.RAVEN,   
# from here, keep SCV and MULE production constant until ~45 workers (author logic)
                UnitTypeId.MARINE,
                UnitTypeId.MARINE,
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.MEDIVAC, # early medivac good?
                UnitTypeId.MARINE,
                UnitTypeId.MARINE,
                # UnitTypeId.SIEGETANK,
                UnitTypeId.BARRACKS,
                UnitTypeId.MARINE, # supply blocked until depot finishes
                UnitTypeId.MARINE,
                UnitTypeId.REFINERY,
                UnitTypeId.MARINE,
                UnitTypeId.MARINE,            # safer baseline scout vs all races (LIBERATOR optional),
                UnitTypeId.VIKINGFIGHTER, 
            ]
        elif build_name == "tvt1":
            # https://lotv.spawningtool.com/build/171779/
            # Standard Terran vs Terran (3 Reaper 2 Hellion) (TvT Economic)
            # Very Standard Reaper Hellion Opening that transitions into Marine-Tank-Raven. As solid it as it gets
            return [
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.BARRACKS,
                UnitTypeId.REFINERY,
                UnitTypeId.REFINERY,
                UnitTypeId.REAPER,
                UnitTypeId.ORBITALCOMMAND,
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.FACTORY,
                UnitTypeId.REAPER,
                UnitTypeId.COMMANDCENTER,
                UnitTypeId.HELLION,
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.REAPER,
                UnitTypeId.STARPORT,
                UnitTypeId.HELLION,
                UnitTypeId.BARRACKSREACTOR,
                UnitTypeId.REFINERY,
                UnitTypeId.FACTORYTECHLAB,
                UnitTypeId.ORBITALCOMMAND,
                UnitTypeId.CYCLONE,
                UnitTypeId.MARINE,
                UnitTypeId.MEDIVAC,
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.MARINE,
                UnitTypeId.MARINE,
                UnitTypeId.SIEGETANK,
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.MARINE,
                UnitTypeId.MARINE,
                UnitTypeId.MARINE,
                UnitTypeId.MARINE,
                UnitTypeId.SIEGETANK,
                UnitTypeId.MARINE,
                UnitTypeId.MARINE,
                UnitTypeId.VIKINGFIGHTER,
                UnitTypeId.MEDIVAC,
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.STARPORTTECHLAB,
                UnitTypeId.SIEGETANK,
                UnitTypeId.RAVEN,
            ]
        elif build_name == "tvt2":
            # tweaked tvt1
            return [
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.BARRACKS,
                UnitTypeId.REFINERY,
                UnitTypeId.REAPER,
                UnitTypeId.BARRACKSREACTOR,
                UnitTypeId.ORBITALCOMMAND,
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.FACTORY,
                UnitTypeId.REAPER,
                UnitTypeId.FACTORYTECHLAB,
                UnitTypeId.COMMANDCENTER,
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.SIEGETANK,
                UnitTypeId.REFINERY,
                UnitTypeId.ORBITALCOMMAND,
                UnitTypeId.MARINE,
                UnitTypeId.MARINE,
                UnitTypeId.STARPORT,
                UnitTypeId.MEDIVAC,
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.MARINE,
                UnitTypeId.MARINE,
                UnitTypeId.SIEGETANK,
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.MARINE,
                UnitTypeId.MARINE,
                UnitTypeId.MARINE,
                UnitTypeId.MARINE,
                UnitTypeId.SIEGETANK,
                UnitTypeId.MARINE,
                UnitTypeId.MARINE,
                UnitTypeId.VIKINGFIGHTER,
                UnitTypeId.MEDIVAC,
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.STARPORTTECHLAB,
                UnitTypeId.SIEGETANK,
                UnitTypeId.RAVEN,
            ]
        elif build_name == 'bottato1':
            return [
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.BARRACKS,
                UnitTypeId.REFINERY,
                UnitTypeId.BARRACKSREACTOR,
                UnitTypeId.MARINE,
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.MARINE,
                UnitTypeId.MARINE,
                UnitTypeId.ORBITALCOMMAND,
                UnitTypeId.REAPER,
                UnitTypeId.REFINERY,
                UnitTypeId.FACTORY,
                UnitTypeId.REAPER,
                UnitTypeId.CYCLONE,
                UnitTypeId.COMMANDCENTER,
                UnitTypeId.FACTORYTECHLAB,
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.REFINERY,
                UnitTypeId.SIEGETANK,
                UnitTypeId.SIEGETANK,
                UnitTypeId.STARPORT,
                UnitTypeId.STARPORTTECHLAB,
                UnitTypeId.RAVEN,
                UnitTypeId.ORBITALCOMMAND,
                UnitTypeId.COMMANDCENTER,
                UnitTypeId.REFINERY,
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.RAVEN,
                UnitTypeId.SIEGETANK,
                UnitTypeId.ENGINEERINGBAY,
                UnitTypeId.RAVEN,
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.SIEGETANK,
                UnitTypeId.ORBITALCOMMAND,
                UnitTypeId.VIKINGFIGHTER,
                UnitTypeId.ORBITALCOMMAND,
                UnitTypeId.ARMORY,
                UnitTypeId.SIEGETANK,
                UnitTypeId.VIKINGFIGHTER,
                UnitTypeId.REFINERY,
                UnitTypeId.REFINERY,
                UnitTypeId.BARRACKSTECHLAB,
                UnitTypeId.FACTORY,
                UnitTypeId.FACTORYTECHLAB,
                UnitTypeId.FACTORY,
                UnitTypeId.VIKINGFIGHTER,
                UnitTypeId.VIKINGFIGHTER,
                UnitTypeId.SIEGETANK,
                UnitTypeId.SIEGETANK,
                UnitTypeId.HELLION,
                UnitTypeId.HELLION,
                UnitTypeId.VIKINGFIGHTER,
                UnitTypeId.HELLION,
                UnitTypeId.HELLION,
                UnitTypeId.FACTORY,
                UnitTypeId.FACTORY,
                UnitTypeId.COMMANDCENTER,
            ]
        return []
