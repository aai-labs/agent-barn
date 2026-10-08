"""Friendly first names, grouped by initial with equal weight per spelling."""

import random

NAMES_BY_INITIAL: tuple[tuple[str, ...], ...] = (
    ("Alfie", "Andy", "Archie", "Arlo", "Amos", "Abe", "Adrian", "Alex", "Aaron", "Arie"),
    ("Benny", "Bobby", "Billy", "Bruno", "Bernie", "Bertie", "Blake", "Brody", "Brandon", "Berny"),
    ("Cody", "Casey", "Chester", "Calvin", "Clark", "Colin", "Cooper", "Cameron", "Carter", "Charlie"),
    ("Denny", "Dougie", "Dean", "Dexter", "Dylan", "Drew", "Darren", "Dominic", "Damien", "Danny"),
    ("Ernie", "Eli", "Evan", "Elliot", "Emmett", "Eddie", "Eric", "Ethan", "Edgar"),
    ("Freddy", "Finny", "Felix", "Finn", "Floyd", "Frank", "Francis", "Fabian", "Fletcher", "Frankie"),
    ("Gary", "Gordy", "Glenn", "Gavin", "Gus", "Graham", "Grant", "Gabe", "Griffin", "George"),
    ("Henry", "Harvey", "Hugo", "Hank", "Hector", "Howard", "Hayden", "Holden", "Hunter", "Harry"),
    ("Ian", "Ike", "Ivan", "Indy", "Iggy", "Isaac", "Idris", "Irving", "Isaiah", "Izzy"),
    ("Joey", "Jamie", "Jesse", "Jack", "Jasper", "Jimmy", "Jordan", "Jonah", "Julian", "Johnny"),
    ("Kirby", "Kyle", "Kevin", "Kody", "Kurt", "Karl", "Keith", "Kane", "Knox", "Kenny"),
    ("Louie", "Lenny", "Larry", "Luca", "Lionel", "Lewis", "Logan", "Landon", "Levi", "Leo"),
    ("Marty", "Monty", "Manny", "Milo", "Morris", "Max", "Mason", "Micah", "Marcus", "Mickey"),
    ("Nelly", "Nate", "Noah", "Nico", "Neil", "Norman", "Nolan", "Nathan", "Nelson", "Nicky"),
    ("Oscar", "Otis", "Owen", "Otto", "Orson", "Ollie", "Orlando", "Omar", "Oliver"),
    ("Petey", "Paddy", "Percy", "Pablo", "Pete", "Paulie", "Preston", "Parker", "Phoenix", "Perry"),
    ("Quinn", "Quentin", "Quinlan", "Quade", "Quincy", "Quinton", "Quest"),
    ("Ronnie", "Rudy", "Ralph", "Remy", "Roger", "Reggie", "Ryan", "Rowan", "Roman", "Ricky"),
    ("Stevie", "Sonny", "Sid", "Simon", "Stan", "Sam", "Shane", "Spencer", "Sebastian", "Sammy"),
    ("Teddy", "Toby", "Tony", "Theo", "Trevor", "Timmy", "Tyler", "Tristan", "Tucker", "Tommy"),
    ("Ulric", "Umar", "Ugo", "Uri", "Ulysses", "Urban", "Usher", "Upton", "Uriah", "Uriel"),
    ("Vinnie", "Victor", "Vince", "Val", "Vernon", "Virgil", "Vaughn", "Vance", "Vincent", "Vinny"),
    ("Wally", "Woody", "Wayne", "Wes", "Walter", "Wilbur", "Wyatt", "Warren", "Wesley", "Willy"),
    ("Xavier", "Xavi", "Xeno", "Xander", "Xerxes"),
    ("Yuri", "Yoshi", "Yancy", "Yosef", "York", "Yannick", "Yves", "Yale", "Yarden", "Yanni"),
    ("Zane", "Zack", "Zeke", "Zed", "Zippy", "Zoltan", "Zion", "Zander", "Zachary", "Ziggy"),
)


def choose_first_name(agent_count: int) -> str:
    return random.choice(NAMES_BY_INITIAL[agent_count % len(NAMES_BY_INITIAL)])
