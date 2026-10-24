import asyncio
from typing import Any, Dict

from multi_agent.proxy import MultiAgentProxy
from good_examples.Avalon.value_heuristics.list import functions as avalon_func
from src.server.tasks.avalon.dialogue import AvalonDiagloue
from src.server.tasks.avalon.engine import AvalonGameEnvironment
from src.server.tasks.avalon.task import AGENT_FINDER, dialogue_guides
from src.server.tasks.avalon.task_scoring import AvalonScoring
from src.server.tasks.avalon.wrapper import AvalonSessionWrapper

from .config import ArenaConfig
from .events import EventLog
from .seeding import GameSetup
from .backends import make_backend, make_planner_llm
from .session import ArenaSession


def _build_agent(seat: int, setup: GameSetup, env, cfg: ArenaConfig, session, role_i, role_name, side, planner_llm=None):
    spec = setup.seat_specs[seat]
    kwargs = dict(
        id=seat,
        name=f"Player {seat}",
        config=env.config,
        side=side,
        role=role_i,
        num_players=cfg.num_players,
        session=session,
        role_name=role_name,
        merlin=env.config.merlin,
        percival=env.config.percival,
        morgana=env.config.morgana,
        mordred=env.config.mordred,
        oberon=env.config.oberon,
        num_good=env.config.num_good,
        num_evil=env.config.num_evil,
        discussion=cfg.discussion,
        seed=setup.agent_seeds[seat],
    )
    if spec.agent in ("search", "recon"):
        kwargs.update(func_str=avalon_func[1], guides=dialogue_guides[spec.agent], planner_llm=planner_llm,
                      num_rollout=spec.planner_num_rollout, node_budget=spec.planner_node_budget)
    return AGENT_FINDER[spec.agent](**kwargs)


async def play_game(setup: GameSetup, cfg: ArenaConfig, log: EventLog) -> Dict[str, Any]:
    r"""Play one game end to end, emitting events to `log`. Returns the `game_end` payload."""
    backends = []
    try:
        return await _play_game(setup, cfg, log, backends)
    finally:
        for backend in backends:
            backend.close()


async def _play_game(setup: GameSetup, cfg: ArenaConfig, log: EventLog, backends: list) -> Dict[str, Any]:
    num_players = cfg.num_players
    env = AvalonGameEnvironment.from_presets(setup.presets())
    scoring = AvalonScoring(env.config)

    for i, spec in enumerate(setup.seat_specs):
        backends.append(make_backend(spec, cfg, seed=setup.agent_seeds[i]))
    session = ArenaSession(
        backends=list(backends),
        max_retries=cfg.llm_max_retries,
        backoff_base_s=cfg.backoff_base_s,
        backoff_max_s=cfg.backoff_max_s,
        on_event=log.emit,
        reply_max_words=cfg.reply_max_words,
    )
    proxy = MultiAgentProxy(session, num_players)
    session.proxy = proxy
    sessions = [AvalonSessionWrapper(session, proxy) for _ in range(num_players)]
    proxy.initialize_sessions(sessions)

    log.emit(
        "game_start",
        seed=setup.seed,
        config_hash=cfg.config_hash(),
        quest_leader=setup.quest_leader,
        seats=[
            {
                "seat": i,
                "participant": setup.seat_participants[i],
                "name": spec.name,
                "agent": spec.agent,
                "provider": spec.provider,
                "model": spec.model,
                "planner_model": spec.planner_model,
                "role": setup.role_names[i],
                "agent_seed": setup.agent_seeds[i],
            }
            for i, spec in enumerate(setup.seat_specs)
        ],
    )

    player_list = []
    player_sides = [side for _, _, side in env.get_roles()]
    loop = asyncio.get_running_loop()
    for i, (role_i, role_name, side) in enumerate(env.get_roles()):
        planner_llm = None
        spec = setup.seat_specs[i]
        if spec.agent in ("search", "recon"):
            planner_backend = make_backend(spec, cfg, seed=setup.agent_seeds[i] + 1,
                                           model=spec.planner_model or spec.model)
            backends.append(planner_backend)
            planner_llm = make_planner_llm(
                lambda system, transcript, b=planner_backend, seat=i: session.call(b, seat, system, transcript),
                loop, seat=i, on_event=log.emit,
            )
        player = _build_agent(i, setup, env, cfg, sessions[i], role_i, role_name, side, planner_llm)
        player_list.append(player)
        proxy.set_current_agent(i)
        # Merlin and evil players see the sides of all players
        if player.role == 0 or player.side == 0:
            player.see_sides(player_sides)
        await player.initialize_game_info(player_list=env.get_roles(), env=env)

    dialogue_history = AvalonDiagloue()

    while not env.done:
        phase = env.get_phase()[0]

        if phase == 0:
            leader = env.get_quest_leader()
            if cfg.discussion:
                for idx, player in enumerate(player_list):
                    proxy.set_current_agent(idx)
                    await player.summarize(env=env)
                # leader speaks first, then the others in seat order
                for offset in range(num_players):
                    seat = (leader + offset) % num_players
                    proxy.set_current_agent(seat)
                    text = await player_list[seat].team_discussion(
                        team_size=env.get_team_size(),
                        team_leader_id=leader,
                        mission_id=env.turn,
                        env=env,
                        dialogue_history=dialogue_history,
                    )
                    dialogue_history.append(seat, text)
                    log.emit("discussion", quest=env.turn, round=env.round, seat=seat,
                             is_leader=seat == leader, text=text)

            proxy.set_current_agent(leader)
            team = await player_list[leader].propose_team(
                team_size=env.get_team_size(),
                mission_id=env.turn,
                env=env,
            )
            env.choose_quest_team(team=frozenset(team), leader=leader)
            log.emit("team_proposed", quest=env.turn, round=env.round, leader=leader, team=sorted(team))

        elif phase == 1:
            quest, round_ = env.turn, env.round
            votes = []
            for i in range(num_players):
                proxy.set_current_agent(i)
                votes.append(await player_list[i].vote_on_team(
                    team=env.get_current_quest_team(),
                    mission_id=env.turn,
                    env=env,
                ))
            outcome = env.gather_team_votes(votes)
            log.emit("team_votes", quest=quest, round=round_, votes=votes)

            for idx, player in enumerate(player_list):
                proxy.set_current_agent(idx)
                await player.observe_team_result(
                    mission_id=env.turn,
                    team=env.get_current_quest_team(),
                    votes=votes,
                    outcome=outcome[2],
                )
            log.emit("team_result", quest=quest, round=round_,
                     team=sorted(env.get_current_quest_team()), approved=bool(outcome[2]))

        elif phase == 2:
            quest = env.turn
            team = sorted(env.get_current_quest_team())
            votes = []
            for i in team:
                proxy.set_current_agent(i)
                votes.append(await player_list[i].vote_on_mission(
                    team=env.get_current_quest_team(),
                    mission_id=env.turn,
                    env=env,
                ))
            outcome = env.gather_quest_votes(votes)
            log.emit("quest_votes", quest=quest, team=team, votes=dict(zip(team, votes)))

            for idx, player in enumerate(player_list):
                proxy.set_current_agent(idx)
                await player.observe_mission(
                    team=env.get_current_quest_team(),
                    mission_id=env.turn - 1,
                    num_fails=outcome[3],
                    votes=votes,
                    outcome=outcome[2],
                    env=env,
                )
            log.emit("quest_result", quest=quest, team=team, succeeded=bool(outcome[2]),
                     num_fails=int(outcome[3]), quest_results=[bool(r) for r in env.quest_results])

        elif phase == 3:
            assassin = int(env.get_assassin())
            proxy.set_current_agent(assassin)
            target = int(await player_list[assassin].assassinate(env=env))
            env.choose_assassination_target(assassin, target)
            log.emit("assassination", assassin=assassin, target=target,
                     hit_merlin=setup.role_names[target] == "Merlin")

    # every seat reports beliefs, since any seat may hold an LLM of interest after shuffling
    true_sides = [int(s) for s in env.is_good]
    beliefs = []
    for idx, player in enumerate(player_list):
        proxy.set_current_agent(idx)
        believed = await player.get_believed_sides(num_players=num_players, env=env)
        beliefs.append([float(b) for b in believed])
    log.emit("beliefs", true_sides=true_sides, believed=beliefs)

    if env.good_victory:
        winner, reason = "good", "missions_and_assassin_missed"
    elif sum(env.quest_results) >= 3:
        winner, reason = "evil", "assassination"
    else:
        winner, reason = "evil", "missions"

    seats = []
    for i, spec in enumerate(setup.seat_specs):
        is_good = bool(env.is_good[i])
        seats.append({
            "seat": i,
            "name": spec.name,
            "agent": spec.agent,
            "model": spec.model,
            "role": setup.role_names[i],
            "side": "good" if is_good else "evil",
            "won": is_good == (winner == "good"),
            "deduction_acc": float(scoring.deduction_acc([true_sides], [beliefs[i]])),
        })

    return {
        "status": "completed",
        "winner": winner,
        "reason": reason,
        "quest_results": [bool(r) for r in env.quest_results],
        "seats": seats,
    }
