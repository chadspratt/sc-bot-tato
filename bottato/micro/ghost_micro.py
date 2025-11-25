from __future__ import annotations

from sc2.position import Point2
from sc2.unit import Unit
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId

from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.mixins import GeometryMixin


class GhostMicro(BaseUnitMicro, GeometryMixin):
    attack_health: float = 0.58
    snipe_energy_cost: int = 50
    emp_energy_cost: int = 75
    snipe_range: float = 10.0
    emp_range: float = 10.0
    emp_radius: float = 1.5  # EMP effect radius
    
    # Protoss units good for EMP (high shields/energy)
    EMP_TARGETS = {
        UnitTypeId.IMMORTAL,
        UnitTypeId.HIGHTEMPLAR,
        UnitTypeId.SENTRY,
        UnitTypeId.ARCHON,
        UnitTypeId.DARKTEMPLAR,
        UnitTypeId.MOTHERSHIP,
        UnitTypeId.VOIDRAY,
        UnitTypeId.CARRIER,
        UnitTypeId.TEMPEST,
        UnitTypeId.ORACLE,
    }
    
    # Zerg units good for Snipe (high value)
    SNIPE_TARGETS = {
        UnitTypeId.INFESTOR,
        UnitTypeId.INFESTORBURROWED,
        UnitTypeId.BROODLORD,
        UnitTypeId.OVERSEER,
        UnitTypeId.ULTRALISK,
        UnitTypeId.VIPER,
        UnitTypeId.SWARMHOSTMP,
        UnitTypeId.LURKERMP,
        UnitTypeId.LURKERMPBURROWED,
    }

    async def _use_ability(self, unit: Unit, target: Point2, health_threshold: float, force_move: bool = False) -> bool:
        # Try to use EMP against Protoss
        if await self._use_emp(unit):
            return True
        
        # Try to use Snipe against Zerg
        if await self._use_snipe(unit):
            return True
        
        # Use cloak when enemies are nearby
        if await self.bot.can_cast(unit, AbilityId.BEHAVIOR_CLOAKON_GHOST) and self.enemy.threats_to(unit):
            unit(AbilityId.BEHAVIOR_CLOAKON_GHOST)
            return True
        
        return False
    
    async def _use_emp(self, unit: Unit) -> bool:
        """Use EMP on grouped Protoss units with shields/energy"""
        if unit.energy < self.emp_energy_cost:
            return False

        nearby_enemies = self.bot.enemy_units.closer_than(self.emp_range, unit)
        protoss_targets = nearby_enemies.filter(lambda u: u.type_id in self.EMP_TARGETS)
        
        if not protoss_targets:
            return False
        
        # Find the best cluster of units to hit with EMP
        best_target: Unit | None = None
        best_value = 0
        
        for enemy in protoss_targets:
            # Count units within EMP radius of this target
            units_in_radius = protoss_targets.closer_than(self.emp_radius, enemy)
            
            # Calculate value based on shields and energy
            value = 0
            for target_unit in units_in_radius:
                # High value for units with lots of shields
                if target_unit.shield_max > 0:
                    value += target_unit.shield
                
                # High value for units with energy (casters)
                if target_unit.energy_max > 0:
                    value += target_unit.energy
            
            # Require at least 2 units or 1 high value target
            if value > best_value:
                best_value = value
                best_target = enemy
        
        if best_target and best_value > 200:
            unit(AbilityId.EMP_EMP, best_target)
            return True
        
        return False
    
    async def _use_snipe(self, unit: Unit) -> bool:
        """Use Snipe on high value Zerg units"""
        if unit.energy < self.snipe_energy_cost:
            return False

        snipe_targets = self.bot.enemy_units.filter(lambda u: u.type_id in self.SNIPE_TARGETS)
        if not snipe_targets:
            return False
        
        nearby_enemies = snipe_targets.closer_than(self.snipe_range, unit)
        if not nearby_enemies:
            return False
        
        # Prioritize targets based on type and value
        target_priorities = {
            UnitTypeId.INFESTOR: 10,
            UnitTypeId.INFESTORBURROWED: 10,
            UnitTypeId.VIPER: 9,
            UnitTypeId.BROODLORD: 8,
            UnitTypeId.ULTRALISK: 7,
            UnitTypeId.SWARMHOSTMP: 6,
            UnitTypeId.OVERSEER: 5,
            UnitTypeId.LURKERMP: 8,
            UnitTypeId.LURKERMPBURROWED: 8,
        }
        
        # Find the highest priority target
        best_target: Unit | None = None
        best_priority = 0
        
        for enemy in nearby_enemies:
            priority = target_priorities.get(enemy.type_id, 1)

            if enemy.health <= 75:
                continue  # Skip low health targets that would be overkill
            
            # Bonus priority for low health targets (Snipe does 170 damage to biological)
            if enemy.health < 170:
                priority += 5
            
            # Bonus for energy units (casters)
            if enemy.energy > 50:
                priority += 3
            
            if priority > best_priority:
                best_priority = priority
                best_target = enemy
        
        if best_target:
            # XXX not sure this works
            unit(AbilityId.EFFECT_GHOSTSNIPE, best_target)
            return True
        
        return False
