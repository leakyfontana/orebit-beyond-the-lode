using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using System.IO;
using System.Runtime.Serialization.Formatters.Binary;
using System.Globalization;

public static class LevelData{
	public static string savefile = Application.persistentDataPath + "/motherloadrecodedsavedata.data";
	public static NumberFormatInfo string_format  = new NumberFormatInfo {NumberGroupSeparator = " "};
	public static int player_money = 20;
	public static bool level_is_already_generated = false;
	public static float player_horizontal_speed;
	public static float player_vertical_speed;
	public static float player_dig_speed;
	public static int player_hp;
	public static int player_max_hp;
	public static float player_fuel;
	public static float player_max_fuel;
	public static float player_radiator;
	public static int player_current_cargo_weight = 0;
	public static int player_total_weight = 1980; //Weight of cargo + player character
	public static int player_max_cargo_weight = 0;
	//Settings
	public static float music_volume = 1f;
	public static float sound_volume = 1f;

	public static Dictionary<string, Dictionary<string, (int price, float effect)>> upgrades = new Dictionary<string, Dictionary<string, (int, float)>>(){
		{"Drill", new Dictionary<string, (int, float)>()
			{
				{"Stock Drill", (2, 2f)},
				{"Silvide Drill", (750, 2.8f)},
				{"Goldium Drill", (2000, 4f)},
				{"Emerald Drill", (5000, 5f)},
				{"Ruby Drill", (20000, 7f)},
				{"Diamond Drill", (100000, 9.5f)},
				{"Amazonite Drill", (500000, 12f)}
			}
		},
		{"Hull", new Dictionary<string, (int, float)>()
			{
				{"Stock Hull", (0, 10f)},
				{"Ironium Hull", (750, 17f)},
				{"Bronzium Hull", (2000, 30f)},
				{"Steel Hull", (5000, 50f)},
				{"Platinium Hull", (20000, 80f)},
				{"Einsteinium Hull", (100000, 120f)},
				{"Energy-Shielded Hull", (500000, 180f)}
			}
		},
		{"Engine", new Dictionary<string, (int, float)>()
			{
				{"Stock Engine", (0, 6f)},
				{"V4 1600 cc", (750, 6.4f)},
				{"V4 2.0 Ltr Turbo", (2000, 6.8f)},
				{"V6 3.8 Ltr", (5000, 7.2f)},
				{"V8 Supercharged 5.0 Ltr", (20000, 7.6f)},
				{"V12 6.0 Ltr", (100000, 8f)},
				{"V16 Jag Engine", (500000, 8.4f)}
			}
		},
		{"Fuel", new Dictionary<string, (int, float)>()
			{
				{"Micro Tank", (0, 10f)},
				{"Medium Tank", (750, 15f)},
				{"Huge Tank", (2000, 25f)},
				{"Gigantic Tank", (5000, 40f)},
				{"Titanic Tank", (20000, 60f)},
				{"Leviathan Tank", (100000, 100f)},
				{"Liquid Compression Tank", (500000, 150f)}
			}
		},
		{"Radiator", new Dictionary<string, (int, float)>()
			{
				{"Stock Fan", (0, 0f)},
				{"Dual Fans", (2000, 0.1f)},
				{"Single Turbine", (5000, 0.25f)},
				{"Dual Turbines", (20000, 0.4f)},
				{"Puron Cooling", (100000, 0.6f)},
				{"Tri-Turbine Freon Array", (500000, 0.8f)}
			}
		},
		{"Cargo", new Dictionary<string, (int, float)>()
			{
				{"Micro Bay", (0, 7f)},
				{"Medium Bay", (750, 15f)},
				{"Huge Bay", (2000, 25f)},
				{"Gigantic Bay", (5000, 40f)},
				{"Titanic Bay", (20000, 70f)},
				{"Leviathan Bay", (100000, 120f)},
			}
		}
	};
	
	public static Dictionary<string, string> current_upgrades = new Dictionary<string, string>(){
		{"Drill", "Stock Drill"},
		{"Hull", "Stock Hull"},
		{"Engine", "Stock Engine"},
		{"Fuel", "Micro Tank"},
		{"Radiator", "Stock Fan"},
		{"Cargo", "Micro Bay"},
	};

	public static Dictionary<string , (int price, string description, string button_to_press)> items = new Dictionary<string, (int, string, string)>(){
		{"Reserve Fuel Tank", (2000,"Portable backup - refills up to 25 Liters instantaneously.","1")},
		{"Hull Repair Nanobots", (7500,"Repairs a maximum of 30 Damage anytime, anywhere.","2")},
		{"Dynamite", (2000,"Blasts clear a small area around your pod.","3")},
		{"Plastic Explosives", (5000,"Creates an enormous explosion, clearing a large area around your pod.","4")},
		{"Quantum Teleporter", (2000,"Teleports you somewhere above surface level.  (results may vary)","5")},
		{"Matter Transmitter", (10000,"Safely and accurately returns you above ground.","6")},
		{"Core Teleporter", (1,"Teleports you directly to the planet\'s core","0")},
	};
	
	public static Dictionary<string, int> player_items = new Dictionary<string, int>(){
		{"Reserve Fuel Tank", 0},
		{"Hull Repair Nanobots", 0},
		{"Dynamite", 0},
		{"Plastic Explosives", 0},
		{"Quantum Teleporter", 0},
		{"Matter Transmitter", 0},
	};
		//{"Core Teleporter", 0},
	
	
	public static List<List<List<int>>> my_map = new List<List<List<int>>>();
	
	public static int earthWidth = 36;
	public static int earthHeight = 600;
	
	public static Dictionary<string, (int ore_value, int weight)> minerals = new Dictionary<string, (int, int)>(){ //string name, (int value, int weight)
		{"Ironium",(30,1)},
		{"Bronzium",(60,1)},
		{"Silverium",(100,1)},
		{"Goldium",(250,2)},
		{"Platinium",(750,3)},
		{"Einsteinium",(2000,4)},
		{"Emerald",(5000,6)},
		{"Ruby",(20000,8)},
		{"Diamond",(100000,10)},
		{"Amazonite",(500000,12)},
		{"Dinosaur Bones",(5000,1)},
		{"Treasure",(12500,1)},
		{"Martian Skeleton",(20000,1)},
		{"Religious Artifact",(50000,1)},
		{"Mr. Natas\' Kevlar Suit",(50000,1)},
		{"Mr. Natas\' Staff of Hell",(100000,1)},
		{"Mr. Natas\' Laser Monacle",(200000,1)},
		{"Satan\'s Hooves",(300000,1)},
		{"Satan\'s Horns",(400000,1)},
		{"Satan\'s Evil Eye (right)",(500000,1)},
		{"Satan\'s Evil Eye (left)",(500000,1)},
		{"Satan\'s Boiler of Eternal Infernos",(600000,1)},
		{"Martian Reward for Restoring Peace",(1000000,1)},
		{"250,000 Shares of Natas HI Inc.",(25000000,1)},
	};
	
	public static List<string> minerals_name_list = new List<string>(){
		"Ironium",
		"Bronzium",
		"Silverium",
		"Goldium",
		"Platinium",
		"Einsteinium",
		"Emerald",
		"Ruby",
		"Diamond",
		"Amazonite"
	};
	
	public static List<string> treasure_name_list = new List<string>(){
		"Dinosaur Bones",
		"Treasure",
		"Martian Skeleton",
		"Religious Artifact",
		"Mr. Natas\' Kevlar Suit",
		"Mr. Natas\' Staff of Hell",
		"Mr. Natas\' Laser Monacle",
		"Satan\'s Hooves",
		"Satan\'s Horns",
		"Satan\'s Evil Eye (right)",
		"Satan\'s Evil Eye (left)",
		"Satan\'s Boiler of Eternal Infernos",
		"Martian Reward for Restoring Peace",
		"250,000 Shares of Natas HI Inc."
	};
		
	public static Dictionary<string, int> player_cargo = new Dictionary<string, int>(){
		{"Ironium", 0},
		{"Bronzium", 0},
		{"Silverium", 0},
		{"Goldium", 0},
		{"Platinium", 0},
		{"Einsteinium", 0},
		{"Emerald", 0},
		{"Ruby", 0},
		{"Diamond", 0},
		{"Amazonite", 0},		
	}; //string name, int quantity
		
	public static List<(string text, string signature, string picture_name, bool displayed)> transmissions = new List<(string, string, string, bool)>(){
		("We forgot to refuel you on the way over!  Drive over to the fuel station (Left) and fill \'er up!\n\nIt\'s been almost impossible to hire decent miners on Mars since all the strange activity started happening around here.  That\'s why we\'re willing to pay you at a premium for your services!\n\nI\'ve given you a basic mining machine to get started with.  Unfortunately, you\'ll be on your own from this point onward, as the settlers who were lucky enough to escape with their lives have fled to safety.  However, all of the shops here have been computerized, so you\'ll still be able to sell your minerals, fuel up, upgrade your pod, and buy special items.\n\nRemember - your job is to collect minerals and bring them back to the surface for processing.  The deeper you dig, the more valuable the minerals you\'ll encounter.\n\nDon\'t forget to refuel - Good Luck!","Mr. Natas","natas", false), //Depth -1
		("Good!  I see you\'re adapting well to the Martian soil!\n\nHere\'s a little something to help you on your way.","Mr. Natas","natas", false), //Depth 500
		("Congratulations on reaching a depth of 1000 ft!  I\'ve wired you a bonus for your excellent work.\n\nWe\'re picking up some heavy vibrations from the planet core - They seem to be causing some earthquakes.  They also seem to be causing some garbled and misdirected transmissions - just ignore them.\n\nKeep up the good work!","Mr. Natas","natas", false), //Depth 1000
		("\n\nThe eyes... oh my god, THE EYES!!!","Unidentified Source","static", false), //Depth 1750
		("I\'m suprised to find another signal around here... I\'m the only miner who hasn\'t disappeared in the past three years.  Next week, I finally get to retire, wealthy, to the moons of jupiter with my wife and three daughters.","Martian Digging Pod #3422-2","miner", false), //Depth 2100
		("Is anyone there?!  I need help badly!!  I can\'t feel my legs - Oh god, he\'s coming back..\n\nOH NO!! PLEASE HELP ME!!! AAAHHHHGGGK!.","Unidentified Source","static", false), //Depth 2500
		("How are you making out, kid? I know you\'re new here, so I though I\'d give you a tip; make sure you don\'t neglect your radiator.  I ran into a Lava pocket a few moments ago, but my twin turbines dissipated the heat amazingly and my hull was barely damaged - Probably saved my life.","Martian Digging Pod #3422-2","miner", false), //Depth 3100
		("Once again, congratulations!  You\'ve made it farther than even I anticipated...\n\nAnyways, I\'ve sent you another bonus. One more thing - Your altimeter is only rated for a depth of around 6000 ft.  After that, you\'ll need to turn back. Really - it\'s just too dangerous.","Mr. Natas","natas", false), //Depth 3500
		("Trapped... in a crevasse.\n\nEarthquake damaged my drill and I\'m out fuel.\n\nThis will probably be my last transmission.\n\nTell my kids.. I love them.. I-\n\nwhat? YOU!?? what are you doing dow-AAARGH!","Martian Digging Pod #3422-2","miner", false), //Depth 4100
		("Oh BABY!!! THIS IS IT!!! I HIT THE MOTHERLOAD!!!!! I\'m rich, I\'m FILTHY rich!!\n\nHey, what the!??  NO!   IT CAN\'T BE!!!!  OH GOD!!","Martian Digging Pod #10043","static", false),//Depth 4500
		("You are violating the terms of your employment!  Turn back immediately!","Mr. Natas","natas", false), //Depth 6200
		("Return to the surface immediately or you\'ll be terminated... er... as in fired!","Mr. Natas","natas", false), //Depth 7000
		("HAHAHA!! YOU FOOL!!!\n\nI told you to turn back... now I have no choice but to kill you.  You\'ve served my factories well, but I think I\'ll take my machine, my money, and your pathetic life now.\n\nSEE YOU IN HELL!!!","Mr. Natas","natas", false), //Depth 9998
		("MWAHAHAHA!  Imbecile!!\n\nYou really think you can defeat me?\n\nI am the master of all EVIL!\n\nBEHOLD MY TRUE FORM!!!","Mr. Natas","natas", false) //Depth 9999
	};
	
	public static void applyShopUpgrades(){
		player_dig_speed = upgrades["Drill"][current_upgrades["Drill"]].effect;
		player_max_hp = (int) upgrades["Hull"][current_upgrades["Hull"]].effect;
		player_horizontal_speed = upgrades["Engine"][current_upgrades["Engine"]].effect;
		player_vertical_speed = upgrades["Engine"][current_upgrades["Engine"]].effect;
		player_max_fuel = upgrades["Fuel"][current_upgrades["Fuel"]].effect;
		player_radiator = upgrades["Radiator"][current_upgrades["Radiator"]].effect;
		player_max_cargo_weight = (int) upgrades["Cargo"][current_upgrades["Cargo"]].effect;
	}

	public static void resetCargo(){
		var minerals = new List<string>(player_cargo.Keys); //I have to do this because I can't edit a dictionnary while inside a foreach loop on the elements of that dictionnary
		foreach(string mineral in minerals){
			Debug.Log(mineral);
			player_cargo[mineral] = 0;
		}
		updateCargoWeight();
	}
	
	public static int sellCargo(){
		int total = 0;
		foreach(KeyValuePair<string, int> entry in player_cargo){
			player_money += minerals[entry.Key].ore_value * entry.Value;
			total += minerals[entry.Key].ore_value * entry.Value;
		}
		resetCargo();
		return total;
	}
	
	public static bool addMineralInCargo(string mineral_name){
		Debug.Log("Adding new mineral: " + mineral_name);
		if (player_current_cargo_weight + minerals[mineral_name].weight > player_max_cargo_weight){
			Debug.Log("No room left in cargo");
			Debug.Log(returnCargoString());
			return false;
		}
		player_cargo[mineral_name] += 1;
		updateCargoWeight();
		Debug.Log(returnCargoString());
		return true;
	}
	
	public static bool removeMineralInCargo(string mineral_name){
		Debug.Log("Removing mineral: " + mineral_name);
		if (player_cargo[mineral_name] <= 0){
			Debug.Log("This mineral is not in cargo");
			return false;
		}
		player_cargo[mineral_name] -= 1;
		updateCargoWeight();
		Debug.Log(returnCargoString());
		return true;
	}
	
	public static void updateCargoWeight(){
		player_current_cargo_weight = 0;
		foreach(KeyValuePair<string, int> mineral in player_cargo){
			player_current_cargo_weight += mineral.Value * minerals[mineral.Key].weight;
		}
		player_total_weight = (player_current_cargo_weight * 10) + 1980;
	}
	
	public static void addTreasureInCargo(string treasure_name){
		Debug.Log("Adding new treasure: " + treasure_name);
		player_money += minerals[treasure_name].ore_value;
	}

	
	public static string returnCargoString(){
		string res = "Cargo: ";
		foreach (string mineral in minerals_name_list){
			if(player_cargo.ContainsKey(mineral)){
				res += mineral + " " + player_cargo[mineral] + ", ";
			}
		}
		return(res);
	}
	
	public static string returnItemString(){
		string res = "Items: ";
		foreach(KeyValuePair<string, int> entry in player_items){
			res += entry.Key + " " + entry.Value + ", ";
		}
		return res;
	}
	
	public static string returnUpgradeString(){
		string res = "Upgrades: ";
		res += current_upgrades["Drill"] + ", ";
		res += current_upgrades["Hull"] + ", ";
		res += current_upgrades["Engine"] + ", ";
		res += current_upgrades["Fuel"] + ", ";
		res += current_upgrades["Radiator"] + ", ";
		res += current_upgrades["Cargo"] + ", ";
		return res;
	}
	
	public static bool tryToBuy(int price){
		if (player_money >= price){
			//GameObject.FindWithTag("Player").GetComponent<PlayerSounds>().playPurchaseSound();
			player_money -= price;
			return true;
		} else {
			return false;
		}
	}
	
	public static void addFuel(int dollar_amount){
		player_fuel = Mathf.Min(player_fuel + dollar_amount, LevelData.player_max_fuel); // 1 dollar = 1 HP
	}
	
	public static void addHull(int dollar_amount){
		player_hp = (int) Mathf.Min(player_hp + Mathf.Ceil((float) dollar_amount / 15), LevelData.player_max_hp); //15 dollar = 1 HP
	}
	
	public static void addItem(string name){
		player_items[name] += 1;
	}
	
	public static void setUpgrade(string category, string upgrade_name){
		current_upgrades[category] = upgrade_name;
		applyShopUpgrades();
	}
	
	public static Dictionary<(int block_rotation, int desired_sprite_rotation), string> blockHalfwayDugFilename = new Dictionary<(int, int), string>(){
		{(0, 0),"Up"},
		{(0, 1),"Left"},
		{(0, 2),"Down"},
		{(0, 3),"Right"},
		{(1, 0),"Right"},
		{(1, 1),"Up"},
		{(1, 2),"Left"},
		{(1, 3),"Down"},
		{(2, 0),"Down"},
		{(2, 1),"Right"},
		{(2, 2),"Up"},
		{(2, 3),"Left"},
		{(3, 0),"Left"},
		{(3, 1),"Down"},
		{(3, 2),"Right"},
		{(3, 3),"Up"},
	};

	public static void initPlayer(){
		Debug.Log("Initializing Player");
		applyShopUpgrades();
		player_hp = player_max_hp;
		if (!(player_fuel == 5))
			player_fuel = player_max_fuel;
		updateCargoWeight();
	}
	
	public static void setVolumeLevels(){
		if(!PlayerPrefs.HasKey("music_volume"))
			PlayerPrefs.SetFloat("music_volume", 1);
		if(!PlayerPrefs.HasKey("sound_volume"))
			PlayerPrefs.SetFloat("sound_volume", 1);
		music_volume = PlayerPrefs.GetFloat("music_volume");
		sound_volume = PlayerPrefs.GetFloat("sound_volume");
	}
	
	public static void saveData(){
		Debug.Log("Saving data");
		SaveDataType save_data = new SaveDataType();
		save_data.player_money = player_money;
		save_data.current_upgrades = current_upgrades;
		save_data.player_items = player_items;
		save_data.my_map = my_map;
		save_data.player_cargo = player_cargo;
		save_data.transmissions = transmissions;
		
		BinaryFormatter formatter = new BinaryFormatter();
		FileStream stream = new FileStream(savefile, FileMode.Create);
		formatter.Serialize(stream, save_data);
		stream.Close();
	}
	
	public static void loadData(){
		Debug.Log("Loading data");
		Debug.Log(savefile);
		
		BinaryFormatter formatter = new BinaryFormatter();
		FileStream stream = new FileStream(savefile, FileMode.Open);
		SaveDataType load_data = formatter.Deserialize(stream) as SaveDataType;
		stream.Close();

		setVolumeLevels();
		player_money = load_data.player_money;
		current_upgrades = load_data.current_upgrades;
		player_items = load_data.player_items;
		my_map = load_data.my_map;
		player_cargo = load_data.player_cargo;
		transmissions = load_data.transmissions;
		level_is_already_generated = true;
	}
	
	public static bool doesSaveFileExist(){
		return(File.Exists(savefile));
	}
	
	public static void setNewGameData(){
		player_money = 20;
		current_upgrades = new Dictionary<string, string>(){
			{"Drill", "Stock Drill"},
			{"Hull", "Stock Hull"},
			{"Engine", "Stock Engine"},
			{"Fuel", "Micro Tank"},
			{"Radiator", "Stock Fan"},
			{"Cargo", "Micro Bay"},
		};
		player_items = new Dictionary<string, int>(){
			{"Reserve Fuel Tank", 0},
			{"Hull Repair Nanobots", 0},
			{"Dynamite", 0},
			{"Plastic Explosives", 0},
			{"Quantum Teleporter", 0},
			{"Matter Transmitter", 0},
		};
		player_cargo = new Dictionary<string, int>(){
			{"Ironium", 0},
			{"Bronzium", 0},
			{"Silverium", 0},
			{"Goldium", 0},
			{"Platinium", 0},
			{"Einsteinium", 0},
			{"Emerald", 0},
			{"Ruby", 0},
			{"Diamond", 0},
			{"Amazonite", 0},		
		};
		
		transmissions = new List<(string, string, string, bool)>(){
			("We forgot to refuel you on the way over!  Drive over to the fuel station (Left) and fill \'er up!\n\nIt\'s been almost impossible to hire decent miners on Mars since all the strange activity started happening around here.  That\'s why we\'re willing to pay you at a premium for your services!\n\nI\'ve given you a basic mining machine to get started with.  Unfortunately, you\'ll be on your own from this point onward, as the settlers who were lucky enough to escape with their lives have fled to safety.  However, all of the shops here have been computerized, so you\'ll still be able to sell your minerals, fuel up, upgrade your pod, and buy special items.\n\nRemember - your job is to collect minerals and bring them back to the surface for processing.  The deeper you dig, the more valuable the minerals you\'ll encounter.\n\nDon\'t forget to refuel - Good Luck!","Mr. Natas","natas", false), //Depth -1
			("Good!  I see you\'re adapting well to the Martian soil!\n\nHere\'s a little something to help you on your way.","Mr. Natas","natas", false), //Depth 500
			("Congratulations on reaching a depth of 1000 ft!  I\'ve wired you a bonus for your excellent work.\n\nWe\'re picking up some heavy vibrations from the planet core - They seem to be causing some earthquakes.  They also seem to be causing some garbled and misdirected transmissions - just ignore them.\n\nKeep up the good work!","Mr. Natas","natas", false), //Depth 1000
			("\n\nThe eyes... oh my god, THE EYES!!!","Unidentified Source","static", false), //Depth 1750
			("I\'m suprised to find another signal around here... I\'m the only miner who hasn\'t disappeared in the past three years.  Next week, I finally get to retire, wealthy, to the moons of jupiter with my wife and three daughters.","Martian Digging Pod #3422-2","miner", false), //Depth 2100
			("Is anyone there?!  I need help badly!!  I can\'t feel my legs - Oh god, he\'s coming back..\n\nOH NO!! PLEASE HELP ME!!! AAAHHHHGGGK!.","Unidentified Source","static", false), //Depth 2500
			("How are you making out, kid? I know you\'re new here, so I though I\'d give you a tip; make sure you don\'t neglect your radiator.  I ran into a Lava pocket a few moments ago, but my twin turbines dissipated the heat amazingly and my hull was barely damaged - Probably saved my life.","Martian Digging Pod #3422-2","miner", false), //Depth 3100
			("Once again, congratulations!  You\'ve made it farther than even I anticipated...\n\nAnyways, I\'ve sent you another bonus. One more thing - Your altimeter is only rated for a depth of around 6000 ft.  After that, you\'ll need to turn back. Really - it\'s just too dangerous.","Mr. Natas","natas", false), //Depth 3500
			("Trapped... in a crevasse.\n\nEarthquake damaged my drill and I\'m out fuel.\n\nThis will probably be my last transmission.\n\nTell my kids.. I love them.. I-\n\nwhat? YOU!?? what are you doing dow-AAARGH!","Martian Digging Pod #3422-2","miner", false), //Depth 4100
			("Oh BABY!!! THIS IS IT!!! I HIT THE MOTHERLOAD!!!!! I\'m rich, I\'m FILTHY rich!!\n\nHey, what the!??  NO!   IT CAN\'T BE!!!!  OH GOD!!","Martian Digging Pod #10043","static", false),//Depth 4500
			("You are violating the terms of your employment!  Turn back immediately!","Mr. Natas","natas", false), //Depth 6200
			("Return to the surface immediately or you\'ll be terminated... er... as in fired!","Mr. Natas","natas", false), //Depth 7000
			("HAHAHA!! YOU FOOL!!!\n\nI told you to turn back... now I have no choice but to kill you.  You\'ve served my factories well, but I think I\'ll take my machine, my money, and your pathetic life now.\n\nSEE YOU IN HELL!!!","Mr. Natas","natas", false), //Depth 9998
			("MWAHAHAHA!  Imbecile!!\n\nYou really think you can defeat me?\n\nI am the master of all EVIL!\n\nBEHOLD MY TRUE FORM!!!","Mr. Natas","natas", false) //Depth 9999
		};
		
		player_fuel = 5;
	}
}
