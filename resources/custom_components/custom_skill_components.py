from __future__ import annotations

from app.data.database.components import ComponentType
from app.data.database.database import DB
from app.data.database.skill_components import SkillComponent, SkillTags
from app.engine import (action, banner, combat_calcs, engine, equations,
                        image_mods, item_funcs, item_system, skill_system,
                        target_system)
from app.engine.game_state import game
from app.engine.objects.unit import UnitObject
from app.utilities import utils, static_random
from app.engine.combat import playback as pb
from app.utilities.enums import Strike
import logging

class DoNothing(SkillComponent):
    nid = 'do_nothing'
    desc = 'does nothing'
    tag = SkillTags.CUSTOM

    expose = ComponentType.Int
    value = 1

class EvalRegeneration(SkillComponent):
    nid = 'eval_regeneration'
    desc = "Unit restores HP at beginning of turn, based on the given evaluation"
    tag = SkillTags.CUSTOM

    expose = ComponentType.String

    def on_upkeep(self, actions, playback, unit):
        max_hp = equations.parser.hitpoints(unit)
        if unit.get_hp() < max_hp:
            from app.engine import evaluate
            try:
                hp_change = int(evaluate.evaluate(self.value, unit))
            except:
                logging.error("Couldn't evaluate %s conditional" % self.value)
                hp_change = 0
            actions.append(action.ChangeHP(unit, hp_change))
            # Playback
            playback.append(pb.HitSound('MapHeal'))
            playback.append(pb.DamageNumbers(unit, -hp_change))
            if hp_change >= 30:
                name = 'MapBigHealTrans'
            elif hp_change >= 15:
                name = 'MapMediumHealTrans'
            else:
                name = 'MapSmallHealTrans'
            playback.append(pb.CastAnim(name))
            
class CannotUseNonMagicItems(SkillComponent):
    nid = 'cannot_use_non_magic_items'
    desc = "Unit cannot use or equip non-magic items"
    tag = SkillTags.BASE

    def available(self, unit, item) -> bool:
        return item_funcs.is_magic(unit, item)
class SelfNihil(SkillComponent):
    nid = 'self_nihil'
    desc = "Skill does not work if the unit has this other skill"
    tag = SkillTags.CUSTOM

    expose = (ComponentType.List, ComponentType.Skill)
    value = []

    ignore_conditional = True

    def condition(self, unit, item):
        all_target_nihils = set(self.value)
        for skill in unit.skills:
          if skill.nid in all_target_nihils:
            return False
        return True
class NihiledBy(SkillComponent):
    nid = 'nihiled_by'
    desc = "Skill does not work against a holder of this other skill"
    tag = SkillTags.CUSTOM

    expose = (ComponentType.List, ComponentType.Skill)
    value = []

    ignore_conditional = True
    _condition = True

    def pre_combat(self, playback, unit, item, target, mode):
        all_target_nihils = set(self.value)
        for skill in target.skills:
            if skill.nid in all_target_nihils:
                self._condition = False
                return
        self._condition = True

    def post_combat(self, playback, unit, item, target, mode):
        self._condition = True

    def condition(self, unit, item):
        return self._condition

    def test_on(self, playback, unit, item, target, mode):
        self.pre_combat(playback, unit, item, target, mode)

    def test_off(self, playback, unit, item, target, mode):
        self._condition = True
class EventAfterCombat(SkillComponent):
    nid = 'event_after_combat'
    desc = 'calls event after combat'
    tag = SkillTags.ADVANCED

    expose = ComponentType.Event
    value = ''

    def end_combat(self, playback, unit: UnitObject, item, target: UnitObject, item2, mode):
        game.events.trigger_specific_event(self.value, unit, target, unit.position, {'item': item, 'item2': item2, 'mode': mode})
class FullMiracle(SkillComponent):
    nid = 'full_miracle'
    desc = "Unit will not die after combat, but will instead be resurrected with full hp"
    tag = SkillTags.CUSTOM

    def cleanup_combat(self, playback, unit, item, target, item2, mode):
        if unit.get_hp() <= 0:
            action.do(action.SetHP(unit, unit.get_max_hp()))
            game.death.miracle(unit)
            action.do(action.TriggerCharge(unit, self.skill))
class LostOnTakeHit(SkillComponent):
    nid = 'lost_on_take_hit'
    desc = "This skill is lost when receiving an attack (it must hit)"
    tag = SkillTags.CUSTOM

    author = 'Lord_Tweed'

    def after_take_strike(self, actions, playback, unit, item, target, item2, mode, attack_info, strike):
        if target and skill_system.check_enemy(unit, target) and strike == Strike.HIT:
            action.do(action.RemoveSkill(unit, self.skill))
class SavageBlowFates(SkillComponent):
    nid = 'savage_blow_fates'
    desc = 'Deals 20% Current HP damage to enemies within the given number of spaces from target.'
    tag = SkillTags.CUSTOM

    expose = ComponentType.Int
    value = 0
    author = 'Lord_Tweed'

    def end_combat(self, playback, unit, item, target, item2, mode):
        if target and skill_system.check_enemy(unit, target):
            r = set(range(self.value+1))
            locations = game.target_system.get_shell({target.position}, r, game.board.bounds)
            for loc in locations:
                target2 = game.board.get_unit(loc)
                if target2 and target2 is not target and skill_system.check_enemy(unit, target2):
                    end_health = target2.get_hp() - (int(target2.get_hp() * .2))
                    action.do(action.SetHP(target2, max(1, end_health)))
class UpkeepSkillGain(SkillComponent):
    nid = 'upkeep_skill_gain'
    desc = "Grants the designated skill at upkeep"
    tag = SkillTags.CUSTOM

    expose = ComponentType.Skill

    def on_upkeep(self, actions, playback, unit):
        action.do(action.AddSkill(unit, self.value))

class EndstepSkillGain(SkillComponent):
    nid = 'endstep_skill_gain'
    desc = "Grants the designated skill at endstep"
    tag = SkillTags.CUSTOM

    expose = ComponentType.Skill

    def on_endstep(self, actions, playback, unit):
        action.do(action.AddSkill(unit, self.value))
class GiveStatusAfterCrit(SkillComponent):
    nid = 'give_status_after_crit'
    desc = "Gives a status to target after critting them"
    tag = SkillTags.CUSTOM

    expose = ComponentType.Skill

    def after_strike(self, actions, playback, unit, item, target, item2, mode, attack_info, strike):
        mark_playbacks = [p for p in playback if p.nid in (
            'mark_crit')]

        if target and any(p.attacker == unit for p in mark_playbacks):
            actions.append(action.AddSkill(target, self.value, unit))
            actions.append(action.TriggerCharge(unit, self.skill))
class UndamagedCondition(SkillComponent):
    nid = 'undamaged_condition'
    desc = "Skill is active while unit has not taken damage this chapter"
    tag = SkillTags.CUSTOM
    author = 'rainlash'

    ignore_conditional = True

    _took_damage_this_combat = False

    def init(self, skill):
        self.skill.data['_has_taken_damage'] = False

    def condition(self, unit):
        return not self.skill.data['_has_taken_damage']

    def after_take_strike(self, actions, playback, unit, item, target, item2, mode, attack_info, strike):
        for act in reversed(actions):
            if isinstance(act, action.ChangeHP) and act.num < 0 and act.unit == unit:
                self._took_damage_this_combat = True
                break

    def end_combat(self, playback, unit, item, target, item2, mode):
        if self._took_damage_this_combat:
            action.do(action.SetObjData(self.skill, '_has_taken_damage', True))
        self._took_damage_this_combat = False

    def on_end_chapter(self, unit, skill):
        self.skill.data['_has_taken_damage'] = False
        self._took_damage_this_combat = False
class GainSkillAfterCrit(SkillComponent):
    nid = 'gain_skill_after_crit'
    desc = "Gives a skill to user after a crit"
    tag = SkillTags.CUSTOM

    expose = ComponentType.Skill

    def end_combat(self, playback, unit, item, target, item2, mode):
        mark_playbacks = [p for p in playback if p.nid in (
            'mark_crit')]
        if target and any(p.attacker is unit and (p.main_attacker is unit or p.attacker is p.main_attacker.strike_partner)
                          for p in mark_playbacks):  # Unit is overall attacker
            action.do(action.AddSkill(unit, self.value, target))
            action.do(action.TriggerCharge(unit, self.skill))
class LoseSkillAfterAnyAttack(SkillComponent):
    nid = 'lose_skill_after_any_attack'
    desc = "This skill is removed from user after an attack during any phase"
    tag = SkillTags.CUSTOM
    
    author = 'Lord_Tweed'

    def end_combat(self, playback, unit, item, target, item2, mode):
        mark_playbacks = [p for p in playback if p.nid in ('mark_miss', 'mark_hit', 'mark_crit')]
        if any(p.attacker is unit for p in mark_playbacks):  # Unit attacked
            action.do(action.RemoveSkill(unit, self.skill))
class LostOnTakeHit(SkillComponent):
    nid = 'lost_on_take_hit'
    desc = "This skill is lost when receiving an attack (it must hit)"
    tag = SkillTags.CUSTOM

    author = 'Lord_Tweed'

    def after_take_strike(self, actions, playback, unit, item, target, item2, mode, attack_info, strike):
        if target and skill_system.check_enemy(unit, target) and strike == Strike.HIT:
            action.do(action.RemoveSkill(unit, self.skill))
class GiveStatusOnTakeHit(SkillComponent):
    nid = 'give_status_on_take_hit'
    desc = "When receiving an attack, give a status to the attacker"
    tag = SkillTags.CUSTOM
    author = 'Lord_Tweed'
    
    expose = ComponentType.Skill

    def after_take_strike(self, actions, playback, unit, item, target, item2, mode, attack_info, strike):
        if target and skill_system.check_enemy(unit, target) and strike == Strike.HIT:
            actions.append(action.AddSkill(target, self.value, unit))
            actions.append(action.TriggerCharge(unit, self.skill))
class SavageStatus(SkillComponent):
    nid = 'savage_status'
    desc = 'Inflicts the given status to enemies within the given number of spaces from target.'
    tag = SkillTags.CUSTOM
    author = 'Lord_Tweed'

    expose = (ComponentType.NewMultipleOptions)
    options = {
        "status": ComponentType.Skill,
        "range": ComponentType.Int,
    }
    
    def __init__(self, value=None):
        self.value = {
            "status": 'Canto',
            "range": 1,
        }
        if value:
            self.value.update(value)

    def end_combat(self, playback, unit, item, target, item2, mode):
        if target and skill_system.check_enemy(unit, target):
            r = set(range(self.value.get('range') + 1))
            locations = game.target_system.get_shell({target.position}, r, game.board.bounds)
            for loc in locations:
                target2 = game.board.get_unit(loc)
                if target2 and target2 is not target and skill_system.check_enemy(unit, target2):
                    action.do(action.AddSkill(target2, self.value.get('status'), unit))
class UpkeepAOESkillGain(SkillComponent):
    nid = 'upkeep_aoe_skill_gain'
    desc = "Grants the designated skill at upkeep to units in an AoE around owner. Can optionally affect user as well."
    tag = SkillTags.CUSTOM
    author = 'Lord_Tweed'

    expose = (ComponentType.NewMultipleOptions)
    options = {
        "skill": ComponentType.Skill,
        "range": ComponentType.Int,
        "affect_self": ComponentType.Bool,
        "target": (ComponentType.MultipleChoice, ('ally', 'enemy', 'any')),
    }
    
    def __init__(self, value=None):
        self.value = {
            "skill": 'Canto',
            "range": 1,
            "affect_self": False,
            "target": 'ally',
        }
        if value:
            self.value.update(value)

    def on_upkeep(self, actions, playback, unit):
        r = set(range(self.value.get('range') + 1))
        locations = game.target_system.get_shell({unit.position}, r, game.board.bounds)
        for loc in locations:
            target2 = game.board.get_unit(loc)
            if target2 and target2 is not unit and self.value.get('target') in ['enemy','any'] and skill_system.check_enemy(unit, target2):
                action.do(action.AddSkill(target2, self.value.get('skill'), unit))
            elif target2 and target2 is not unit and self.value.get('target') in ['ally','any'] and skill_system.check_ally(unit, target2):
                action.do(action.AddSkill(target2, self.value.get('skill'), unit))

        if self.value.get('affect_self'):
            action.do(action.AddSkill(unit, self.value.get('skill'), unit))