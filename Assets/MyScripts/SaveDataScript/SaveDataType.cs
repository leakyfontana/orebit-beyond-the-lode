using System.Collections;
using System.Collections.Generic;
using UnityEngine;

[System.Serializable]
public class SaveDataType{
	public int player_money;
	public Dictionary<string, string> current_upgrades;
	public Dictionary<string, int> player_items;
	public List<List<List<int>>> my_map;
	public Dictionary<string, int> player_cargo;
	public List<(string text, string signature, string picture_name, bool displayed)> transmissions;
}
