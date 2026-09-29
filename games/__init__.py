from games.beauty_contest import BeautyContest
from games.matching_pennies import MatchingPennies
from games.monty_hall import MontyHall
from games.prisoners_dilemma import PrisonersDilemma
from games.rps import RockPaperScissors
from games.ultimatum import Ultimatum

GAMES = {g.name: g for g in (PrisonersDilemma, MatchingPennies, RockPaperScissors,
                             Ultimatum, BeautyContest, MontyHall)}
