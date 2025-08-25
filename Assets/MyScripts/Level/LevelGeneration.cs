using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TMPro;

public class LevelGeneration : MonoBehaviour{	
	public void generateLevel(){		
		Debug.Log("Generating the level");
		LevelData.my_map = new List<List<List<int>>>();
		generateEarth();
		//Utils.log3DIntList(LevelData.my_map);
		string res = "";
		foreach(var x in LevelData.my_map){
			foreach(var y in x){
				foreach(var z in y){
					res += z;
				}
				res += "\n";
			}
			res += "\n\n\n";
		}
	}
	
	public void setTexture(string file){ //For example, "1018"
		//LevelData.my_map[0][0].GetComponent<Renderer>().material.mainTexture = Resources.Load("1018") as Texture2D;
		GetComponent<Renderer>().material.mainTexture = Resources.Load(file) as Texture2D;
	}
		
	void generateEarth(){
		System.Random random = new System.Random();
		for (int i = 0; i < LevelData.earthWidth; i++){
			LevelData.my_map.Add(new List<List<int>>());
			for (int j = 0; j < LevelData.earthHeight; j++){
				LevelData.my_map[i].Add(new List<int>());
				LevelData.my_map[i][j].Add(-100);
				LevelData.my_map[i][j].Add(-100);
			}
		}
		int mineralRate = 65;
		var _loc2_ = 0;
		while(_loc2_ < LevelData.earthWidth){
			var _loc1_ = 0;
			while(_loc1_ < LevelData.earthHeight){
				LevelData.my_map[_loc2_][_loc1_][1] = random.Next(4);
				if(_loc1_ < 5){
					LevelData.my_map[_loc2_][_loc1_][0] = 0; //Air above
				}
				else if(_loc1_ == 5){
					LevelData.my_map[_loc2_][_loc1_][0] = random.Next(2) - 2; //Grass
				}
				else if(_loc1_ == LevelData.earthHeight - 12){
					LevelData.my_map[_loc2_][_loc1_][0] = random.Next(2) - 7; //Stalactite
				}
				else if(_loc1_ >= LevelData.earthHeight - 11 && _loc1_ < LevelData.earthHeight - 5){
					LevelData.my_map[_loc2_][_loc1_][0] = -999; //Blank
				}
				else if(_loc1_ == LevelData.earthHeight - 5){
					LevelData.my_map[_loc2_][_loc1_][0] = - (9 + random.Next(4)); //Souls1, Souls2, Souls3, Souls4
				}
				else if(_loc1_ > LevelData.earthHeight - 5){
					LevelData.my_map[_loc2_][_loc1_][0] = -8; //Darkness
				}
				else{
					if(random.Next(5) == 0){ //If normal lucky
						if(random.Next(5) == 0){ //If very lucky
							if(random.Next(5) == 0){ //If ultra lucky
								if(random.Next(4) == 0 && _loc1_ > 80){ //If uber lucky and height > 80
									LevelData.my_map[_loc2_][_loc1_][0] = random.Next(4) + 16;
									if(LevelData.my_map[_loc2_][_loc1_][0] == 17){ //Cancels the satan's hooves? don't know why, maybe no graphics
										LevelData.my_map[_loc2_][_loc1_][1] = 0;
									}
								}
								else{
									LevelData.my_map[_loc2_][_loc1_][0] = System.Math.Min(random.Next(((int)(_loc1_ / mineralRate)) + 2) + 8,15); //Spawns a mineral Minimum between this and 15
								}
							}
							else{
								LevelData.my_map[_loc2_][_loc1_][0] = System.Math.Min(random.Next(((int)(_loc1_ / mineralRate)) + 2) + 7,15); //Spawns a mineral Minimum between this and 15
							}
						}
						else{
							LevelData.my_map[_loc2_][_loc1_][0] = System.Math.Min(random.Next(((int)(_loc1_ / mineralRate)) + 2) + 6,15); //Spawns a mineral Minimum between this and 15
							//loc1 is current height
							//MineralRate is 65
							//+2 is to make the level higher
							//6,15 is also to make the level higher, if more lucky, more high tier minerals
						}
					}
					else{ //If not lucky
						LevelData.my_map[_loc2_][_loc1_][0] = random.Next(5) + 1;
						if(_loc1_ * 1.5 > LevelData.earthHeight / 3){ // If you're low enough loc1 = earthHeigt/4.5
							if (random.Next(((int)((((double) LevelData.earthHeight - _loc1_) / LevelData.earthHeight) * 15))) == 0){ //The deeper you are, the more frequent it is true
								if((double)_loc1_ / 2 * 1.5 > (double)LevelData.earthHeight / 3 && random.Next(2) == 0){
									if((double)_loc1_ / 3 * 1.5 > (double)LevelData.earthHeight / 3 && random.Next(2) == 0){
										LevelData.my_map[_loc2_][_loc1_][0] = 31; //31 is "1"
									}
									else{
										LevelData.my_map[_loc2_][_loc1_][0] = 28 + random.Next(3); //Lava
									}
								}
								else{
								LevelData.my_map[_loc2_][_loc1_][0] = 25 + random.Next(3); //Rock
								}
							}
						}
					}
					if(random.Next(4) == 0){ //One chance out of four that it is empty
						LevelData.my_map[_loc2_][_loc1_][0] = 0;
					}
				}
				_loc1_ = _loc1_ + 1;
			}
			_loc2_ = _loc2_ + 1;
		}
		LevelData.my_map[LevelData.earthWidth - 3][LevelData.earthHeight - 12][0] = 0;
		LevelData.my_map[LevelData.earthWidth - 4][LevelData.earthHeight - 12][0] = 0;
		LevelData.my_map[3][3][0] = -125;
		LevelData.my_map[4][3][0] = -126;
		LevelData.my_map[5][3][0] = -127;
		LevelData.my_map[3][4][0] = -128;
		LevelData.my_map[4][4][0] = -129;
		LevelData.my_map[5][4][0] = -130;
		LevelData.my_map[2][5][0] = -3;
		LevelData.my_map[3][5][0] = -4;
		LevelData.my_map[4][5][0] = -4;
		LevelData.my_map[5][5][0] = -5;
		LevelData.my_map[10][2][0] = -110;
		LevelData.my_map[11][2][0] = -111;
		LevelData.my_map[12][2][0] = -112;
		LevelData.my_map[13][2][0] = -113;
		LevelData.my_map[10][3][0] = -114;
		LevelData.my_map[11][3][0] = -115;
		LevelData.my_map[12][3][0] = -116;
		LevelData.my_map[13][3][0] = -117;
		LevelData.my_map[10][4][0] = -118;
		LevelData.my_map[11][4][0] = -119;
		LevelData.my_map[12][4][0] = -120;
		LevelData.my_map[13][4][0] = -121;
		LevelData.my_map[9][5][0] = -3;
		LevelData.my_map[10][5][0] = -4;
		LevelData.my_map[11][5][0] = -4;
		LevelData.my_map[12][5][0] = -4;
		LevelData.my_map[13][5][0] = -4;
		LevelData.my_map[14][5][0] = -5;
		LevelData.my_map[25][2][0] = -101;
		LevelData.my_map[22][3][0] = -102;
		LevelData.my_map[23][3][0] = -103;
		LevelData.my_map[24][3][0] = -104;
		LevelData.my_map[25][3][0] = -105;
		LevelData.my_map[22][4][0] = -106;
		LevelData.my_map[23][4][0] = -107;
		LevelData.my_map[24][4][0] = -108;
		LevelData.my_map[25][4][0] = -109;
		LevelData.my_map[21][5][0] = -3;
		LevelData.my_map[22][5][0] = -4;
		LevelData.my_map[23][5][0] = -4;
		LevelData.my_map[24][5][0] = -4;
		LevelData.my_map[25][5][0] = -4;
		LevelData.my_map[26][5][0] = -5;
		LevelData.my_map[30][3][0] = -131;
		LevelData.my_map[31][3][0] = -132;
		LevelData.my_map[32][3][0] = -133;
		LevelData.my_map[30][4][0] = -134;
		LevelData.my_map[31][4][0] = -135;
		LevelData.my_map[32][4][0] = -136;
		LevelData.my_map[30][5][0] = -3;
		LevelData.my_map[31][5][0] = -4;
		LevelData.my_map[32][5][0] = -4;
		LevelData.my_map[33][5][0] = -5;
	}
}
