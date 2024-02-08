from __future__ import annotations

from app.data.database.components import ComponentType
from app.data.database.database import DB
from app.data.database.difficulty_modes import RNGOption
from app.data.database.item_components import ItemComponent, ItemTags
from app.engine import (action, banner, combat_calcs, engine, equations,
                        image_mods, item_funcs, item_system, skill_system,
                        target_system)
from app.utilities import (static_random)
from app.engine.game_state import game
from app.engine.objects.unit import UnitObject
from app.engine.combat import playback as pb
from app.engine.movement import movement_funcs
from app.utilities import utils
import logging


class DoNothing(ItemComponent):
    nid = 'do_nothing'
    desc = 'does nothing'
    tag = ItemTags.CUSTOM

    expose = ComponentType.Int
    value = 1

class ShoveFlexible(ItemComponent):
    nid = 'shove_flex'
    desc = "Item shoves target on hit up to X spaces"
    tag = ItemTags.SPECIAL

    expose = ComponentType.Int
    value = 1

    def _check_shove(self, unit_to_move, anchor_pos, magnitude):
        while(magnitude != 0):
            offset_x = utils.clamp(unit_to_move.position[0] - anchor_pos[0], -1, 1)
            offset_y = utils.clamp(unit_to_move.position[1] - anchor_pos[1], -1, 1)
            new_position = (unit_to_move.position[0] + offset_x * magnitude,
                            unit_to_move.position[1] + offset_y * magnitude)

            mcost = movement_funcs.get_mcost(unit_to_move, new_position)
            if game.board.check_bounds(new_position) and \
                    not game.board.get_unit(new_position) and \
                    mcost <= equations.parser.movement(unit_to_move):
                return new_position
            if magnitude < 0:
                magnitude += 1
            else:
                magnitude -= 1
        return False

    def on_hit(self, actions, playback, unit, item, target, target_pos, mode, attack_info):
        if not skill_system.ignore_forced_movement(target):
            new_position = self._check_shove(target, unit.position, self.value)
            if new_position:
                actions.append(action.ForcedMovement(target, new_position))
                playback.append(pb.ShoveHit(unit, item, target))

class ShoveFlexibleStops(ItemComponent):
    nid = 'shove_flex_stops'
    desc = "Item shoves target on hit up to X spaces, can be shortened by obstacles"
    tag = ItemTags.SPECIAL

    expose = ComponentType.Int
    value = 1

    def _check_shove(self, unit_to_move, anchor_pos, magnitude):
        curr_magnitude = 0
        ret_position = None
        while(abs(curr_magnitude) < abs(magnitude)):
            if magnitude < 0:
                curr_magnitude -= 1
            else:
                curr_magnitude += 1
            offset_x = utils.clamp(unit_to_move.position[0] - anchor_pos[0], -1, 1)
            offset_y = utils.clamp(unit_to_move.position[1] - anchor_pos[1], -1, 1)
            new_position = (unit_to_move.position[0] + offset_x * curr_magnitude,
                            unit_to_move.position[1] + offset_y * curr_magnitude)

            mcost = movement_funcs.get_mcost(unit_to_move, new_position)
            if game.board.check_bounds(new_position) and \
                    not game.board.get_unit(new_position) and \
                    mcost <= equations.parser.movement(unit_to_move):
                ret_position = new_position
            else:
                magnitude = 0
        if not ret_position:
            return False
        return ret_position

    def on_hit(self, actions, playback, unit, item, target, target_pos, mode, attack_info):
        if not skill_system.ignore_forced_movement(target):
            new_position = self._check_shove(target, unit.position, self.value)
            if new_position:
                actions.append(action.ForcedMovement(target, new_position))
                playback.append(pb.ShoveHit(unit, item, target))

class GoldCost(ItemComponent):
    nid = 'gold_cost'
    desc = "Item subtracts the specified amount of gold upon use. If unit does not have enough gold the item will not be usable."
    tag = ItemTags.USES

    expose = ComponentType.Int
    value = 1

    def available(self, unit, item) -> bool:
        return game.get_money() >= self.value

    def start_combat(self, playback, unit, item, target, mode):
        action.do(action.GainMoney(game.current_party, -self.value))

    def reverse_use(self, unit, item):
        action.do(action.GainMoney(game.current_party, self.value))
class Backdash(ItemComponent):
    nid = 'backdash'
    desc = 'Unit shoves *itself* backwards from the target point.'
    tag = ItemTags.SPECIAL
    author = 'mag'

    expose = ComponentType.Int
    value = 1

    def _check_dash(self, target, user, magnitude):
        tpos = target.position
        upos = user.position
        offset = utils.tmult(utils.tclamp(utils.tuple_sub(upos, tpos), (-1, -1), (1, 1)), magnitude)
        npos = utils.tuple_add(upos, offset)

        mcost_user = movement_funcs.get_mcost(user, npos)
        if game.board.check_bounds(npos) and not game.board.get_unit(npos) and \
                mcost_user <= equations.parser.movement(user):
            return npos
        return None

    def target_restrict(self, unit, item, def_pos, splash) -> bool:
        target = game.board.get_unit(def_pos)
        if not target:
            return False
        new_position = self._check_dash(target, unit, self.value)
        if new_position:
            return True
        return False

    def on_hit(self, actions, playback, unit, item, target, target_pos, mode, attack_info):
        if not skill_system.ignore_forced_movement(unit):
            new_position = self._check_dash(target, unit, self.value)
            if new_position:
                actions.append(action.ForcedMovement(unit, new_position))
                playback.append(pb.ShoveHit(unit, item, target))
                   
class BlastAOE(ItemComponent):
    nid = 'blast_aoe'
    desc = "Blast extends outwards the specified number of tiles."
    tag = ItemTags.CUSTOM

    expose = ComponentType.Int  # Radius
    value = 1

    def _get_power(self, unit) -> int:
        empowered_splash = skill_system.empower_splash(unit)
        return self.value + 1 + empowered_splash

    def splash(self, unit, item, position) -> tuple:
        ranges = set(range(self._get_power(unit)))
        splash = target_system.find_manhattan_spheres(ranges, position[0], position[1])
        splash = {pos for pos in splash if game.tilemap.check_bounds(pos)}
        from app.engine import item_system
        if item_system.is_spell(unit, item):
            # spell blast
            splash = [game.board.get_unit(s) for s in splash]
            splash = [s.position for s in splash if s]
            return None, splash
        else:
            # regular blast
            splash = [game.board.get_unit(s) for s in splash if s != position]
            splash = [s.position for s in splash if s]
            return position if game.board.get_unit(position) else None, splash

    def splash_positions(self, unit, item, position) -> set:
        ranges = set(range(self._get_power(unit)))
        splash = target_system.find_manhattan_spheres(ranges, position[0], position[1])
        splash = {pos for pos in splash if game.tilemap.check_bounds(pos)}
        return splash
                
class RallyBlastAOE(BlastAOE, ItemComponent):
    nid = 'rally_blast_aoe'
    desc = "Gives Blast AOE that only hits allies, but not unit"
    tag = ItemTags.AOE

    def splash(self, unit, item, position) -> tuple:
        ranges = set(range(self._get_power(unit)))
        splash = target_system.find_manhattan_spheres(ranges, position[0], position[1])
        splash = {pos for pos in splash if game.tilemap.check_bounds(pos)}
        from app.engine import skill_system
        splash = [game.board.get_unit(s) for s in splash]
        splash = [s.position for s in splash if s and skill_system.check_ally(unit, s) and s is not unit]
        return None, splash
        
class ShoveOnEndCombatInitiate(ItemComponent):
    nid = 'shove_on_end_combat_initiate'
    desc = "Item shoves target at the end of combat, only on initiation"
    tag = ItemTags.CUSTOM

    expose = ComponentType.Int
    value = 1

    def _check_shove(self, unit_to_move, anchor_pos, magnitude):
        offset_x = utils.clamp(unit_to_move.position[0] - anchor_pos[0], -1, 1)
        offset_y = utils.clamp(unit_to_move.position[1] - anchor_pos[1], -1, 1)
        new_position = (unit_to_move.position[0] + offset_x * magnitude,
                        unit_to_move.position[1] + offset_y * magnitude)

        mcost = movement_funcs.get_mcost(unit_to_move, new_position)
        if game.board.check_bounds(new_position) and \
                not game.board.get_unit(new_position) and \
                mcost <= equations.parser.movement(unit_to_move):
            return new_position
        return False
    
    def end_combat(self, playback, unit, item, target, mode):
        if not skill_system.ignore_forced_movement(target) and mode and mode == 'attack':
            new_position = self._check_shove(target, unit.position, self.value)
            if new_position:
                action.do(action.ForcedMovement(target, new_position))
class Bullrush(ItemComponent):
    nid = 'bullrush'
    desc = "Item moves user in a straight line but can't land on obstacles. Provide a list of walkable terrain types"
    tag = ItemTags.CUSTOM

    expose = (ComponentType.List, ComponentType.Terrain)

    def _specially_traversable(self, unit, pos) -> int:
        """
        returns 0 if a square is ordinarily traversable
        returns 1 if a square is warpable
        returns 2 if it's not traversable and we shouldn't be able to warp over it
        """
        if movement_funcs.check_traversable(unit, pos):
            return 0
        elif game.tilemap.get_terrain(pos) in self.value:
            return 1
        else:
            return 2

    def _determine_valid_endpoints(self, unit):
        """returns dict of {target: endpoint} that can be warped to"""
        valid_endpoints = {}
        # down, up, left, right
        directions = [(0, 1), (0, -1), (-1, 0), (1, 0)]
        movement = equations.parser.movement(unit)
        # should be impossible?
        if not unit.position:
            return valid_endpoints
        for delta in directions:
            current_pos = unit.position
            targetable_adj_pos = utils.tuple_add(current_pos, delta)[:]
            if not game.board.check_bounds(targetable_adj_pos): continue # if the neighbor pos doesn't even exist, skip
            if self._specially_traversable(unit, targetable_adj_pos) != 0: continue # if the neighboring pos isn't a warpable wall, skip
            while True: # if and only if there's eventually a space we can stop, and we only warp over valid walls in the meantime, this target is ok
                if delta == (0, 1):
                    current_pos = utils.tuple_add((current_pos[0], current_pos[1] + (movement - 1)), delta)
                elif delta == (0, -1):
                    current_pos = utils.tuple_add((current_pos[0], current_pos[1] - (movement - 1)), delta)
                elif delta == (-1, 0):
                    current_pos = utils.tuple_add((current_pos[0] - (movement - 1), current_pos[1]), delta)
                elif delta == (1, 0):
                    current_pos = utils.tuple_add((current_pos[0] + (movement - 1), current_pos[1]), delta)
                if not game.board.check_bounds(current_pos): break # gone off the map, skip
                status_of_current_square = self._specially_traversable(unit, current_pos)
                if status_of_current_square == 2: break # crossing over an unwarpable tile, skip
                elif status_of_current_square == 0: # made it to a standing tile, we're good
                    valid_endpoints[targetable_adj_pos] = current_pos
                break
        return valid_endpoints

    def valid_targets(self, unit, item) -> set:
        return {pos for pos, _ in self._determine_valid_endpoints(unit).items()}

    #check for target restrict invalid endpoint
    def target_restrict(self, unit, item, pos, splash) -> bool:
        possible_endpoints = self._determine_valid_endpoints(unit)
        endpoint = possible_endpoints.get(pos, None)
        if unit and endpoint:
            if movement_funcs.check_traversable(unit, endpoint):
                return True
        return False

    def on_hit(self, actions, playback, unit, item, target, target_pos, mode, attack_info):
        possible_endpoints = self._determine_valid_endpoints(unit)
        endpoint = possible_endpoints.get(target_pos, None)
        current_occupant = game.board.get_unit(endpoint)
        if endpoint:
            actions.append(action.Swoosh(target, endpoint))
            if bool(current_occupant) == True:
                new_pos = target_system.get_nearest_open_tile(current_occupant, endpoint)
                action.do(action.ForcedMovement(current_occupant, new_pos))
class MagicWeaponRank(ItemComponent):
    nid = 'magic_weapon_rank'
    desc = "Item is a magic weapon, and has a wrank"
    requires = ['weapon_type']
    tag = ItemTags.CUSTOM

    expose = ComponentType.WeaponRank

    def weapon_rank(self, unit, item):
        return self.value

    def available(self, unit, item):
        required_wexp = DB.weapon_ranks.get(self.value).requirement
        weapon_type = item_system.weapon_type(unit, item)
        optional_tag = 'Magician'
        if weapon_type:
            return (unit.wexp.get(weapon_type) >= required_wexp or optional_tag in unit.tags)
        else:  # If no weapon type, then always available
            return True      
class WeaponTypeExempt(ItemComponent):
    nid = 'weapon_type_exempt'
    desc = "Categorizes a weapon type but does not require the wielder to be able to use that weapon type"
    tag = ItemTags.WEAPON

    expose = ComponentType.WeaponType

    def weapon_type(self, unit, item):
        return self.value

    def available(self, unit, item) -> bool:
        return True
class ShoveFlexibleOnEndCombatInitiate(ItemComponent):
    nid = 'shove_flexible_on_end_combat_initiate'
    desc = "Item shoves target at the end of combat, only on initiation. Target will stop if they hit a wall."
    tag = ItemTags.CUSTOM

    expose = ComponentType.Int
    value = 1

    def _check_shove(self, unit_to_move, anchor_pos, magnitude):
        curr_magnitude = 0
        ret_position = None
        while(abs(curr_magnitude) < abs(magnitude)):
            if magnitude < 0:
                curr_magnitude -= 1
            else:
                curr_magnitude += 1
            offset_x = utils.clamp(unit_to_move.position[0] - anchor_pos[0], -1, 1)
            offset_y = utils.clamp(unit_to_move.position[1] - anchor_pos[1], -1, 1)
            new_position = (unit_to_move.position[0] + offset_x * curr_magnitude,
                            unit_to_move.position[1] + offset_y * curr_magnitude)

            mcost = movement_funcs.get_mcost(unit_to_move, new_position)
            if game.board.check_bounds(new_position) and \
                    not game.board.get_unit(new_position) and \
                    mcost <= equations.parser.movement(unit_to_move):
                ret_position = new_position
            else:
                magnitude = 0
        if not ret_position:
            return False
        return ret_position
    
    def end_combat(self, playback, unit, item, target, mode):
        if not skill_system.ignore_forced_movement(target) and mode and mode == 'attack':
            new_position = self._check_shove(target, unit.position, self.value)
            if new_position:
                action.do(action.ForcedMovement(target, new_position))         
class Locked2(ItemComponent):
    nid = 'locked_2'
    desc = 'Item cannot be taken or dropped from a units inventory. However, the trade command can be used to rearrange its position, and event commands can remove the item.'
    tag = ItemTags.CUSTOM

    def locked(self, unit, item) -> bool:
        return True

    def unstealable(self, unit, item) -> bool:
        return True