using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TMPro;

public class TilesLoader : MonoBehaviour
{
	public GameObject block_storage;
	public GameObject traversable_block_base;
	public GameObject diggable_block_base;
	public Dictionary<string, Sprite> sprite_dict = new Dictionary<string, Sprite>();
	
	static IDictionary<string, string> TunnelTiles;
	public static List<(string name, int ore_value, int weight)> minerals_list = new List<(string, int, int)>(){
		("Ironium",30,1),
		("Bronzium",60,1),
		("Silverium",100,1),
		("Goldium",250,2),
		("Platinium",750,3),
		("Einsteinium",2000,4),
		("Emerald",5000,6),
		("Ruby",20000,8),
		("Diamond",100000,10),
		("Amazonite",500000,12),
		("Dinosaur Bones",1000,1),
		("Treasure",5000,1),
		("Martian Skeleton",10000,1),
		("Religious Artifact",50000,1),
		("Mr. Natas\' Kevlar Suit",50000,1),
		("Mr. Natas\' Staff of Hell",100000,1),
		("Mr. Natas\' Laser Monacle",200000,1),
		("Satan\'s Hooves",300000,1),
		("Satan\'s Horns",400000,1),
		("Satan\'s Evil Eye (right)",500000,1),
		("Satan\'s Evil Eye (left)",500000,1),
		("Satan\'s Boiler of Eternal Infernos",600000,1),
		("Martian Reward for Restoring Peace",1000000,1),
		("250,000 Shares of Natas HI Inc.",25000000,1),
	};	

	 // Start is called before the first frame update
	void Start(){
		if(!LevelData.level_is_already_generated)
			GetComponent<LevelGeneration>().generateLevel();
		initializeTunnelTilesDictionnary();
		loadBlocks();
		LevelData.initPlayer();
	}
	
	public (string filename, string name, int rotation, string layer, int ore_value, int weight) getTileDataFromLevelData(int x, int y){
		if(LevelData.my_map[x][y][0] != 0){
			int n = LevelData.my_map[x][y][0];
			if(n < 6 && n > -1){
				return ("Dirt"+n, "Dirt", LevelData.my_map[x][y][1], "Diggable", 0, 0);
			}
			if(n == -100){ //Block is already dug
				return ("Half", "Half", LevelData.my_map[x][y][1], "Diggable", 0, 0);
			}
			if(n == -999){
				return ("Blank","Blank", 0, "Traversable", 0, 0);
			}
			if(n < -100){
				return ("Shop" + (- n), "Shop", 2, "Traversable", 0, 0);
			}
			if(n < 0 && n > -3){
				return ("Grass" + (- n), "Grass", 2, "Diggable", 0, 0);
			}
			if(n > -6 && n < -2){
				return ("Pavement" + (- n - 3), "Pavement", 2, "Invincible", 0, 0);
			}
			if(n > 24 && n < 28){
				return ("Rock" + ((int)n - 24), "Rock", LevelData.my_map[x][y][1], "Diggable", 0, 0);
			}
			if(n > 27 && n < 31){
				return ("Lava" + ((int)n - 27), "Lava", LevelData.my_map[x][y][1], "Diggable", 0, 0);
			}
			if(n == 31){
				return ("Gas", "Gas", LevelData.my_map[x][y][1], "Diggable", 0, 0);
			}
			if(n < -5 && n > -8){
				return ("Stalactite" + (- n - 5), "Stalactite", 2, "Invincible", 0, 0);
			}
			if(n == -8){
				return ("Darkness", "Darkness", 0, "Invincible", 0, 0);
			}
			if(n == -9){
				return ("Souls1", "Souls", 2, "Invincible", 0, 0);
			}
			if(n == -10){
				return ("Souls2", "Souls", 2, "Invincible", 0, 0);
			}
			if(n == -11){
				return ("Souls3", "Souls", 2, "Invincible", 0, 0);
			}
			if(n == -12){
				return ("Souls4", "Souls", 2, "Invincible", 0, 0);
			}
			return (minerals_list[n - 6].name, minerals_list[n - 6].name, LevelData.my_map[x][y][1], "Diggable", minerals_list[n - 6].ore_value, minerals_list[n - 6].weight);
		}
		if(y < 5){
			return ("Empty", "Empty", 0, "Traversable", 0, 0);
		}
		if(y > LevelData.earthHeight - 13){
			return ("Empty", "Empty", 0, "Traversable", 0, 0);
		}
		return(getTunnelTileGraphicName(x, y));
	}
	
	private (string filename, string name, int rotation, string layer, int ore_value, int weight) getTunnelTileGraphicName(int x, int y){
		//The filename for tunnels is constitued of 0 and 1 according to the presence of absence of a wall in that location around the current block.
		//It goes from top-left to bottom-right
		string tilename = "";
		List<int> tiles_around = new List<int>();
		int getValue(int x, int y){
			if (x < 0 || x >= LevelData.earthWidth || y < 0 || y >= LevelData.earthHeight || LevelData.my_map[x][y][0] != 0){
				return 1;
			}
			return 0;
		}
		//Find out if there is earth blocks around a block
		tilename += getValue(x - 1, y - 1);
		tilename += getValue(x    , y - 1);
		tilename += getValue(x + 1, y - 1);
		
		tilename += getValue(x - 1, y    );
		tilename += getValue(x + 1, y    );
		
		tilename += getValue(x - 1, y + 1);
		tilename += getValue(x    , y + 1);
		tilename += getValue(x + 1, y + 1);
		return ("DirtConnectors/" + TunnelTiles[tilename], "DirtConnector", 2, "Traversable", 0, 0);
	}
	
	public void loadBlocks(){
		for (int i = 0 ; i < LevelData.earthWidth; i++){
			for (int j = 0; j < LevelData.earthHeight; j++){
				createNewBlock(i, j);
			}
		}
	}
	
	public void createNewBlock(int x, int y){
		(string filename, string name, int rotation, string layer, int ore_value, int weight) tile_data = getTileDataFromLevelData(x, y);
		GameObject base_block = tile_data.layer == "Traversable"? traversable_block_base : diggable_block_base;
		GameObject block = Instantiate(base_block, new Vector3(x + 0.5f, -y + 0.5f, 0), Quaternion.Euler(0, 0, 90 * (tile_data.rotation - 2)));
		if(sprite_dict.ContainsKey("Blocks/" + tile_data.filename)){
			block.GetComponent<SpriteRenderer>().sprite = sprite_dict["Blocks/" + tile_data.filename];
		}
		else{
			Texture2D texture = Resources.Load<Texture2D>("Blocks/" + tile_data.filename) as Texture2D;
			Sprite my_sprite = Sprite.Create(
				texture,
				new Rect(0, 0, 50, 50), // section of texture to use
				new Vector2(0.5f, 0.5f), // pivot in centre
				50 // pixels per unity tile grid unit
			);
			sprite_dict["Blocks/" + tile_data.filename] = my_sprite;
			block.GetComponent<SpriteRenderer>().sprite = my_sprite;
		}
		block.transform.SetParent(block_storage.transform);
		if (tile_data.layer == "Diggable"){
			block.GetComponent<BlockData>().isDiggable = true;
		}
		else if (tile_data.layer == "Traversable"){
			block.GetComponent<BlockData>().isTraversable = true;
		}
		else if (tile_data.layer == "Invincible"){
			//block.GetComponent<BlockData>().isDiggable = true; //Not sure why I put this there, if it causes problems maybe I should put that line back in
			block.GetComponent<BlockData>().isInvincible = true;
		}
		block.GetComponent<BlockData>().filename = tile_data.filename;
		block.GetComponent<BlockData>().object_name = tile_data.name;
		block.GetComponent<BlockData>().ore_value = tile_data.ore_value;
		block.GetComponent<BlockData>().weight = tile_data.weight;
		block.GetComponent<BlockData>().map_x = x;
		block.GetComponent<BlockData>().map_y = y;
		block.GetComponent<BlockData>().rotation = tile_data.rotation;
		GetComponent<TilesManager>().allBlocks[(x, y)] = block;
	}
	
	public void updateTraversableTileData(int x, int y){
		if (GetComponent<TilesManager>().allBlocks.ContainsKey((x, y))){
			GameObject block = GetComponent<TilesManager>().allBlocks[(x, y)];
			if (block.GetComponent<BlockData>().isTraversable){
				(string filename, string name, int rotation, string layer, int ore_value, int weight) block_data = getTileDataFromLevelData(x, y);
				if(sprite_dict.ContainsKey("Blocks/" + block_data.filename)){
					block.GetComponent<SpriteRenderer>().sprite = sprite_dict["Blocks/" + block_data.filename];
				}
				else{
					Texture2D texture = Resources.Load<Texture2D>("Blocks/" + block_data.filename) as Texture2D;
					Sprite my_sprite = Sprite.Create(
						texture,
						new Rect(0, 0, 50, 50), // section of texture to use
						new Vector2(0.5f, 0.5f), // pivot in centre
						50 // pixels per unity tile grid unit
					);
					sprite_dict["Blocks/" + block_data.filename] = my_sprite;
					block.GetComponent<SpriteRenderer>().sprite = my_sprite;
				}
				block.GetComponent<BlockData>().filename = block_data.filename;
			}
		}
	}
		
	private void initializeTunnelTilesDictionnary(){
		//This list contains every possible configuration of tiles around a block, and finds a graphic that correspond to that combination
		TunnelTiles = new Dictionary<string, string>();
		TunnelTiles.Add("00000000", "0");
		TunnelTiles.Add("00000001", "1");
		TunnelTiles.Add("00000010", "16");
		TunnelTiles.Add("00000011", "16");
		TunnelTiles.Add("00000100", "2");
		TunnelTiles.Add("00000101", "5");
		TunnelTiles.Add("00000110", "16");
		TunnelTiles.Add("00000111", "16");
		TunnelTiles.Add("00001000", "17");
		TunnelTiles.Add("00001001", "17");
		TunnelTiles.Add("00001010", "28");
		TunnelTiles.Add("00001011", "28");
		TunnelTiles.Add("00001100", "20");
		TunnelTiles.Add("00001101", "20");
		TunnelTiles.Add("00001110", "28");
		TunnelTiles.Add("00001111", "28");
		TunnelTiles.Add("00010000", "19");
		TunnelTiles.Add("00010001", "27");
		TunnelTiles.Add("00010010", "29");
		TunnelTiles.Add("00010011", "29");
		TunnelTiles.Add("00010100", "19");
		TunnelTiles.Add("00010101", "27");
		TunnelTiles.Add("00010110", "29");
		TunnelTiles.Add("00010111", "29");
		TunnelTiles.Add("00011000", "40");
		TunnelTiles.Add("00011001", "40");
		TunnelTiles.Add("00011010", "42");
		TunnelTiles.Add("00011011", "42");
		TunnelTiles.Add("00011100", "40");
		TunnelTiles.Add("00011101", "40");
		TunnelTiles.Add("00011110", "42");
		TunnelTiles.Add("00011111", "42");
		TunnelTiles.Add("00100000", "4");
		TunnelTiles.Add("00100001", "6");
		TunnelTiles.Add("00100010", "26");
		TunnelTiles.Add("00100011", "26");
		TunnelTiles.Add("00100100", "9");
		TunnelTiles.Add("00100101", "13");
		TunnelTiles.Add("00100110", "26");
		TunnelTiles.Add("00100111", "26");
		TunnelTiles.Add("00101000", "17");
		TunnelTiles.Add("00101001", "17");
		TunnelTiles.Add("00101010", "28");
		TunnelTiles.Add("00101011", "28");
		TunnelTiles.Add("00101100", "20");
		TunnelTiles.Add("00101101", "20");
		TunnelTiles.Add("00101110", "28");
		TunnelTiles.Add("00101111", "28");
		TunnelTiles.Add("00110000", "22");
		TunnelTiles.Add("00110001", "35");
		TunnelTiles.Add("00110010", "37");
		TunnelTiles.Add("00110011", "37");
		TunnelTiles.Add("00110100", "22");
		TunnelTiles.Add("00110101", "35");
		TunnelTiles.Add("00110110", "37");
		TunnelTiles.Add("00110111", "37");
		TunnelTiles.Add("00111000", "40");
		TunnelTiles.Add("00111001", "40");
		TunnelTiles.Add("00111010", "42");
		TunnelTiles.Add("00111011", "42");
		TunnelTiles.Add("00111100", "40");
		TunnelTiles.Add("00111101", "40");
		TunnelTiles.Add("00111110", "42");
		TunnelTiles.Add("00111111", "42");
		TunnelTiles.Add("01000000", "18");
		TunnelTiles.Add("01000001", "23");
		TunnelTiles.Add("01000010", "41");
		TunnelTiles.Add("01000011", "41");
		TunnelTiles.Add("01000100", "24");
		TunnelTiles.Add("01000101", "34");
		TunnelTiles.Add("01000110", "41");
		TunnelTiles.Add("01000111", "41");
		TunnelTiles.Add("01001000", "31");
		TunnelTiles.Add("01001001", "31");
		TunnelTiles.Add("01001010", "43");
		TunnelTiles.Add("01001011", "43");
		TunnelTiles.Add("01001100", "38");
		TunnelTiles.Add("01001101", "38");
		TunnelTiles.Add("01001110", "43");
		TunnelTiles.Add("01001111", "43");
		TunnelTiles.Add("01010000", "30");
		TunnelTiles.Add("01010001", "39");
		TunnelTiles.Add("01010010", "44");
		TunnelTiles.Add("01010011", "44");
		TunnelTiles.Add("01010100", "30");
		TunnelTiles.Add("01010101", "39");
		TunnelTiles.Add("01010110", "44");
		TunnelTiles.Add("01010111", "44");
		TunnelTiles.Add("01011000", "45");
		TunnelTiles.Add("01011001", "45");
		TunnelTiles.Add("01011010", "46");
		TunnelTiles.Add("01011011", "46");
		TunnelTiles.Add("01011100", "45");
		TunnelTiles.Add("01011101", "45");
		TunnelTiles.Add("01011110", "46");
		TunnelTiles.Add("01011111", "46");
		TunnelTiles.Add("01100000", "18");
		TunnelTiles.Add("01100001", "23");
		TunnelTiles.Add("01100010", "41");
		TunnelTiles.Add("01100011", "41");
		TunnelTiles.Add("01100100", "24");
		TunnelTiles.Add("01100101", "34");
		TunnelTiles.Add("01100110", "41");
		TunnelTiles.Add("01100111", "41");
		TunnelTiles.Add("01101000", "31");
		TunnelTiles.Add("01101001", "31");
		TunnelTiles.Add("01101010", "43");
		TunnelTiles.Add("01101011", "43");
		TunnelTiles.Add("01101100", "38");
		TunnelTiles.Add("01101101", "38");
		TunnelTiles.Add("01101110", "43");
		TunnelTiles.Add("01101111", "43");
		TunnelTiles.Add("01110000", "30");
		TunnelTiles.Add("01110001", "39");
		TunnelTiles.Add("01110010", "44");
		TunnelTiles.Add("01110011", "44");
		TunnelTiles.Add("01110100", "30");
		TunnelTiles.Add("01110101", "39");
		TunnelTiles.Add("01110110", "44");
		TunnelTiles.Add("01110111", "44");
		TunnelTiles.Add("01111000", "45");
		TunnelTiles.Add("01111001", "45");
		TunnelTiles.Add("01111010", "46");
		TunnelTiles.Add("01111011", "46");
		TunnelTiles.Add("01111100", "45");
		TunnelTiles.Add("01111101", "45");
		TunnelTiles.Add("01111110", "46");
		TunnelTiles.Add("01111111", "46");
		TunnelTiles.Add("10000000", "3");
		TunnelTiles.Add("10000001", "10");
		TunnelTiles.Add("10000010", "21");
		TunnelTiles.Add("10000011", "21");
		TunnelTiles.Add("10000100", "8");
		TunnelTiles.Add("10000101", "12");
		TunnelTiles.Add("10000110", "21");
		TunnelTiles.Add("10000111", "21");
		TunnelTiles.Add("10001000", "25");
		TunnelTiles.Add("10001001", "25");
		TunnelTiles.Add("10001010", "36");
		TunnelTiles.Add("10001011", "36");
		TunnelTiles.Add("10001100", "33");
		TunnelTiles.Add("10001101", "33");
		TunnelTiles.Add("10001110", "36");
		TunnelTiles.Add("10001111", "36");
		TunnelTiles.Add("10010000", "19");
		TunnelTiles.Add("10010001", "27");
		TunnelTiles.Add("10010010", "29");
		TunnelTiles.Add("10010011", "29");
		TunnelTiles.Add("10010100", "19");
		TunnelTiles.Add("10010101", "27");
		TunnelTiles.Add("10010110", "29");
		TunnelTiles.Add("10010111", "29");
		TunnelTiles.Add("10011000", "40");
		TunnelTiles.Add("10011001", "40");
		TunnelTiles.Add("10011010", "42");
		TunnelTiles.Add("10011011", "42");
		TunnelTiles.Add("10011100", "40");
		TunnelTiles.Add("10011101", "40");
		TunnelTiles.Add("10011110", "42");
		TunnelTiles.Add("10011111", "42");
		TunnelTiles.Add("10100000", "7");
		TunnelTiles.Add("10100001", "14");
		TunnelTiles.Add("10100010", "32");
		TunnelTiles.Add("10100011", "32");
		TunnelTiles.Add("10100100", "11");
		TunnelTiles.Add("10100101", "15");
		TunnelTiles.Add("10100110", "32");
		TunnelTiles.Add("10100111", "32");
		TunnelTiles.Add("10101000", "25");
		TunnelTiles.Add("10101001", "25");
		TunnelTiles.Add("10101010", "36");
		TunnelTiles.Add("10101011", "36");
		TunnelTiles.Add("10101100", "33");
		TunnelTiles.Add("10101101", "33");
		TunnelTiles.Add("10101110", "36");
		TunnelTiles.Add("10101111", "36");
		TunnelTiles.Add("10110000", "22");
		TunnelTiles.Add("10110001", "35");
		TunnelTiles.Add("10110010", "37");
		TunnelTiles.Add("10110011", "37");
		TunnelTiles.Add("10110100", "22");
		TunnelTiles.Add("10110101", "35");
		TunnelTiles.Add("10110110", "37");
		TunnelTiles.Add("10110111", "37");
		TunnelTiles.Add("10111000", "40");
		TunnelTiles.Add("10111001", "40");
		TunnelTiles.Add("10111010", "42");
		TunnelTiles.Add("10111011", "42");
		TunnelTiles.Add("10111100", "40");
		TunnelTiles.Add("10111101", "40");
		TunnelTiles.Add("10111110", "42");
		TunnelTiles.Add("10111111", "42");
		TunnelTiles.Add("11000000", "18");
		TunnelTiles.Add("11000001", "23");
		TunnelTiles.Add("11000010", "41");
		TunnelTiles.Add("11000011", "41");
		TunnelTiles.Add("11000100", "24");
		TunnelTiles.Add("11000101", "34");
		TunnelTiles.Add("11000110", "41");
		TunnelTiles.Add("11000111", "41");
		TunnelTiles.Add("11001000", "31");
		TunnelTiles.Add("11001001", "31");
		TunnelTiles.Add("11001010", "43");
		TunnelTiles.Add("11001011", "43");
		TunnelTiles.Add("11001100", "38");
		TunnelTiles.Add("11001101", "38");
		TunnelTiles.Add("11001110", "43");
		TunnelTiles.Add("11001111", "43");
		TunnelTiles.Add("11010000", "30");
		TunnelTiles.Add("11010001", "39");
		TunnelTiles.Add("11010010", "44");
		TunnelTiles.Add("11010011", "44");
		TunnelTiles.Add("11010100", "30");
		TunnelTiles.Add("11010101", "39");
		TunnelTiles.Add("11010110", "44");
		TunnelTiles.Add("11010111", "44");
		TunnelTiles.Add("11011000", "45");
		TunnelTiles.Add("11011001", "45");
		TunnelTiles.Add("11011010", "46");
		TunnelTiles.Add("11011011", "46");
		TunnelTiles.Add("11011100", "45");
		TunnelTiles.Add("11011101", "45");
		TunnelTiles.Add("11011110", "46");
		TunnelTiles.Add("11011111", "46");
		TunnelTiles.Add("11100000", "18");
		TunnelTiles.Add("11100001", "23");
		TunnelTiles.Add("11100010", "41");
		TunnelTiles.Add("11100011", "41");
		TunnelTiles.Add("11100100", "24");
		TunnelTiles.Add("11100101", "34");
		TunnelTiles.Add("11100110", "41");
		TunnelTiles.Add("11100111", "41");
		TunnelTiles.Add("11101000", "31");
		TunnelTiles.Add("11101001", "31");
		TunnelTiles.Add("11101010", "43");
		TunnelTiles.Add("11101011", "43");
		TunnelTiles.Add("11101100", "38");
		TunnelTiles.Add("11101101", "38");
		TunnelTiles.Add("11101110", "43");
		TunnelTiles.Add("11101111", "43");
		TunnelTiles.Add("11110000", "30");
		TunnelTiles.Add("11110001", "39");
		TunnelTiles.Add("11110010", "44");
		TunnelTiles.Add("11110011", "44");
		TunnelTiles.Add("11110100", "30");
		TunnelTiles.Add("11110101", "39");
		TunnelTiles.Add("11110110", "44");
		TunnelTiles.Add("11110111", "44");
		TunnelTiles.Add("11111000", "45");
		TunnelTiles.Add("11111001", "45");
		TunnelTiles.Add("11111010", "46");
		TunnelTiles.Add("11111011", "46");
		TunnelTiles.Add("11111100", "45");
		TunnelTiles.Add("11111101", "45");
		TunnelTiles.Add("11111110", "46");
		TunnelTiles.Add("11111111", "46");
	}
}
 