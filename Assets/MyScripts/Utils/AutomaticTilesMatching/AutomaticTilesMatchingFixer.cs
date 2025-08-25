using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class AutomaticTilesMatchingFixer : MonoBehaviour
{
	List<List<string>> TunnelTiles = new List<List<string>>();
	public GameObject main;
	public GameObject b0;
	public GameObject b1;
	public GameObject b2;
	public GameObject b3;
	public GameObject b4;
	public GameObject b5;
	public GameObject b6;
	public GameObject b7;
	public string current_string_1;
	public string current_string_2;
	public int current_index = 0;
    // Start is called before the first frame update
    void Start()
    {
        TunnelTiles.Add(new List<string>(){"00000000", "0"});
		TunnelTiles.Add(new List<string>(){"00000001", "1"});
		TunnelTiles.Add(new List<string>(){"00000010", "16"});
		TunnelTiles.Add(new List<string>(){"00000011", "16"});
		TunnelTiles.Add(new List<string>(){"00000100", "2"});
		TunnelTiles.Add(new List<string>(){"00000101", "5"});
		TunnelTiles.Add(new List<string>(){"00000110", "16"});
		TunnelTiles.Add(new List<string>(){"00000111", "16"});
		TunnelTiles.Add(new List<string>(){"00001000", "17"});
		TunnelTiles.Add(new List<string>(){"00001001", "17"});
		TunnelTiles.Add(new List<string>(){"00001010", "28"});
		TunnelTiles.Add(new List<string>(){"00001011", "28"});
		TunnelTiles.Add(new List<string>(){"00001100", "20"});
		TunnelTiles.Add(new List<string>(){"00001101", "20"});
		TunnelTiles.Add(new List<string>(){"00001110", "28"});
		TunnelTiles.Add(new List<string>(){"00001111", "28"});
		TunnelTiles.Add(new List<string>(){"00010000", "19"});
		TunnelTiles.Add(new List<string>(){"00010001", "27"});
		TunnelTiles.Add(new List<string>(){"00010010", "29"});
		TunnelTiles.Add(new List<string>(){"00010011", "29"});
		TunnelTiles.Add(new List<string>(){"00010100", "19"});
		TunnelTiles.Add(new List<string>(){"00010101", "27"});
		TunnelTiles.Add(new List<string>(){"00010110", "29"});
		TunnelTiles.Add(new List<string>(){"00010111", "29"});
		TunnelTiles.Add(new List<string>(){"00011000", "40"});
		TunnelTiles.Add(new List<string>(){"00011001", "40"});
		TunnelTiles.Add(new List<string>(){"00011010", "42"});
		TunnelTiles.Add(new List<string>(){"00011011", "42"});
		TunnelTiles.Add(new List<string>(){"00011100", "40"});
		TunnelTiles.Add(new List<string>(){"00011101", "40"});
		TunnelTiles.Add(new List<string>(){"00011110", "42"});
		TunnelTiles.Add(new List<string>(){"00011111", "42"});
		TunnelTiles.Add(new List<string>(){"00100000", "4"});
		TunnelTiles.Add(new List<string>(){"00100001", "6"});
		TunnelTiles.Add(new List<string>(){"00100010", "26"});
		TunnelTiles.Add(new List<string>(){"00100011", "26"});
		TunnelTiles.Add(new List<string>(){"00100100", "9"});
		TunnelTiles.Add(new List<string>(){"00100101", "13"});
		TunnelTiles.Add(new List<string>(){"00100110", "26"});
		TunnelTiles.Add(new List<string>(){"00100111", "26"});
		TunnelTiles.Add(new List<string>(){"00101000", "17"});
		TunnelTiles.Add(new List<string>(){"00101001", "17"});
		TunnelTiles.Add(new List<string>(){"00101010", "28"});
		TunnelTiles.Add(new List<string>(){"00101011", "28"});
		TunnelTiles.Add(new List<string>(){"00101100", "20"});
		TunnelTiles.Add(new List<string>(){"00101101", "20"});
		TunnelTiles.Add(new List<string>(){"00101110", "28"});
		TunnelTiles.Add(new List<string>(){"00101111", "28"});
		TunnelTiles.Add(new List<string>(){"00110000", "22"});
		TunnelTiles.Add(new List<string>(){"00110001", "35"});
		TunnelTiles.Add(new List<string>(){"00110010", "37"});
		TunnelTiles.Add(new List<string>(){"00110011", "37"});
		TunnelTiles.Add(new List<string>(){"00110100", "22"});
		TunnelTiles.Add(new List<string>(){"00110101", "35"});
		TunnelTiles.Add(new List<string>(){"00110110", "37"});
		TunnelTiles.Add(new List<string>(){"00110111", "37"});
		TunnelTiles.Add(new List<string>(){"00111000", "40"});
		TunnelTiles.Add(new List<string>(){"00111001", "40"});
		TunnelTiles.Add(new List<string>(){"00111010", "42"});
		TunnelTiles.Add(new List<string>(){"00111011", "42"});
		TunnelTiles.Add(new List<string>(){"00111100", "40"});
		TunnelTiles.Add(new List<string>(){"00111101", "40"});
		TunnelTiles.Add(new List<string>(){"00111110", "42"});
		TunnelTiles.Add(new List<string>(){"00111111", "42"});
		TunnelTiles.Add(new List<string>(){"01000000", "18"});
		TunnelTiles.Add(new List<string>(){"01000001", "23"});
		TunnelTiles.Add(new List<string>(){"01000010", "41"});
		TunnelTiles.Add(new List<string>(){"01000011", "41"});
		TunnelTiles.Add(new List<string>(){"01000100", "24"});
		TunnelTiles.Add(new List<string>(){"01000101", "34"});
		TunnelTiles.Add(new List<string>(){"01000110", "41"});
		TunnelTiles.Add(new List<string>(){"01000111", "41"});
		TunnelTiles.Add(new List<string>(){"01001000", "31"});
		TunnelTiles.Add(new List<string>(){"01001001", "31"});
		TunnelTiles.Add(new List<string>(){"01001010", "43"});
		TunnelTiles.Add(new List<string>(){"01001011", "43"});
		TunnelTiles.Add(new List<string>(){"01001100", "38"});
		TunnelTiles.Add(new List<string>(){"01001101", "38"});
		TunnelTiles.Add(new List<string>(){"01001110", "43"});
		TunnelTiles.Add(new List<string>(){"01001111", "43"});
		TunnelTiles.Add(new List<string>(){"01010000", "30"});
		TunnelTiles.Add(new List<string>(){"01010001", "39"});
		TunnelTiles.Add(new List<string>(){"01010010", "44"});
		TunnelTiles.Add(new List<string>(){"01010011", "44"});
		TunnelTiles.Add(new List<string>(){"01010100", "30"});
		TunnelTiles.Add(new List<string>(){"01010101", "39"});
		TunnelTiles.Add(new List<string>(){"01010110", "44"});
		TunnelTiles.Add(new List<string>(){"01010111", "44"});
		TunnelTiles.Add(new List<string>(){"01011000", "45"});
		TunnelTiles.Add(new List<string>(){"01011001", "45"});
		TunnelTiles.Add(new List<string>(){"01011010", "46"});
		TunnelTiles.Add(new List<string>(){"01011011", "46"});
		TunnelTiles.Add(new List<string>(){"01011100", "45"});
		TunnelTiles.Add(new List<string>(){"01011101", "45"});
		TunnelTiles.Add(new List<string>(){"01011110", "46"});
		TunnelTiles.Add(new List<string>(){"01011111", "46"});
		TunnelTiles.Add(new List<string>(){"01100000", "18"});
		TunnelTiles.Add(new List<string>(){"01100001", "23"});
		TunnelTiles.Add(new List<string>(){"01100010", "41"});
		TunnelTiles.Add(new List<string>(){"01100011", "41"});
		TunnelTiles.Add(new List<string>(){"01100100", "24"});
		TunnelTiles.Add(new List<string>(){"01100101", "34"});
		TunnelTiles.Add(new List<string>(){"01100110", "41"});
		TunnelTiles.Add(new List<string>(){"01100111", "41"});
		TunnelTiles.Add(new List<string>(){"01101000", "31"});
		TunnelTiles.Add(new List<string>(){"01101001", "31"});
		TunnelTiles.Add(new List<string>(){"01101010", "43"});
		TunnelTiles.Add(new List<string>(){"01101011", "43"});
		TunnelTiles.Add(new List<string>(){"01101100", "38"});
		TunnelTiles.Add(new List<string>(){"01101101", "38"});
		TunnelTiles.Add(new List<string>(){"01101110", "43"});
		TunnelTiles.Add(new List<string>(){"01101111", "43"});
		TunnelTiles.Add(new List<string>(){"01110000", "30"});
		TunnelTiles.Add(new List<string>(){"01110001", "39"});
		TunnelTiles.Add(new List<string>(){"01110010", "44"});
		TunnelTiles.Add(new List<string>(){"01110011", "44"});
		TunnelTiles.Add(new List<string>(){"01110100", "30"});
		TunnelTiles.Add(new List<string>(){"01110101", "39"});
		TunnelTiles.Add(new List<string>(){"01110110", "44"});
		TunnelTiles.Add(new List<string>(){"01110111", "44"});
		TunnelTiles.Add(new List<string>(){"01111000", "45"});
		TunnelTiles.Add(new List<string>(){"01111001", "45"});
		TunnelTiles.Add(new List<string>(){"01111010", "46"});
		TunnelTiles.Add(new List<string>(){"01111011", "46"});
		TunnelTiles.Add(new List<string>(){"01111100", "45"});
		TunnelTiles.Add(new List<string>(){"01111101", "45"});
		TunnelTiles.Add(new List<string>(){"01111110", "46"});
		TunnelTiles.Add(new List<string>(){"01111111", "46"});
		TunnelTiles.Add(new List<string>(){"10000000", "3"});
		TunnelTiles.Add(new List<string>(){"10000001", "10"});
		TunnelTiles.Add(new List<string>(){"10000010", "21"});
		TunnelTiles.Add(new List<string>(){"10000011", "21"});
		TunnelTiles.Add(new List<string>(){"10000100", "8"});
		TunnelTiles.Add(new List<string>(){"10000101", "12"});
		TunnelTiles.Add(new List<string>(){"10000110", "21"});
		TunnelTiles.Add(new List<string>(){"10000111", "21"});
		TunnelTiles.Add(new List<string>(){"10001000", "25"});
		TunnelTiles.Add(new List<string>(){"10001001", "25"});
		TunnelTiles.Add(new List<string>(){"10001010", "36"});
		TunnelTiles.Add(new List<string>(){"10001011", "36"});
		TunnelTiles.Add(new List<string>(){"10001100", "33"});
		TunnelTiles.Add(new List<string>(){"10001101", "33"});
		TunnelTiles.Add(new List<string>(){"10001110", "36"});
		TunnelTiles.Add(new List<string>(){"10001111", "36"});
		TunnelTiles.Add(new List<string>(){"10010000", "19"});
		TunnelTiles.Add(new List<string>(){"10010001", "27"});
		TunnelTiles.Add(new List<string>(){"10010010", "29"});
		TunnelTiles.Add(new List<string>(){"10010011", "29"});
		TunnelTiles.Add(new List<string>(){"10010100", "19"});
		TunnelTiles.Add(new List<string>(){"10010101", "27"});
		TunnelTiles.Add(new List<string>(){"10010110", "29"});
		TunnelTiles.Add(new List<string>(){"10010111", "29"});
		TunnelTiles.Add(new List<string>(){"10011000", "40"});
		TunnelTiles.Add(new List<string>(){"10011001", "40"});
		TunnelTiles.Add(new List<string>(){"10011010", "42"});
		TunnelTiles.Add(new List<string>(){"10011011", "42"});
		TunnelTiles.Add(new List<string>(){"10011100", "40"});
		TunnelTiles.Add(new List<string>(){"10011101", "40"});
		TunnelTiles.Add(new List<string>(){"10011110", "42"});
		TunnelTiles.Add(new List<string>(){"10011111", "42"});
		TunnelTiles.Add(new List<string>(){"10100000", "7"});
		TunnelTiles.Add(new List<string>(){"10100001", "14"});
		TunnelTiles.Add(new List<string>(){"10100010", "32"});
		TunnelTiles.Add(new List<string>(){"10100011", "32"});
		TunnelTiles.Add(new List<string>(){"10100100", "11"});
		TunnelTiles.Add(new List<string>(){"10100101", "15"});
		TunnelTiles.Add(new List<string>(){"10100110", "32"});
		TunnelTiles.Add(new List<string>(){"10100111", "32"});
		TunnelTiles.Add(new List<string>(){"10101000", "25"});
		TunnelTiles.Add(new List<string>(){"10101001", "25"});
		TunnelTiles.Add(new List<string>(){"10101010", "36"});
		TunnelTiles.Add(new List<string>(){"10101011", "36"});
		TunnelTiles.Add(new List<string>(){"10101100", "33"});
		TunnelTiles.Add(new List<string>(){"10101101", "33"});
		TunnelTiles.Add(new List<string>(){"10101110", "36"});
		TunnelTiles.Add(new List<string>(){"10101111", "36"});
		TunnelTiles.Add(new List<string>(){"10110000", "22"});
		TunnelTiles.Add(new List<string>(){"10110001", "35"});
		TunnelTiles.Add(new List<string>(){"10110010", "37"});
		TunnelTiles.Add(new List<string>(){"10110011", "37"});
		TunnelTiles.Add(new List<string>(){"10110100", "22"});
		TunnelTiles.Add(new List<string>(){"10110101", "35"});
		TunnelTiles.Add(new List<string>(){"10110110", "37"});
		TunnelTiles.Add(new List<string>(){"10110111", "37"});
		TunnelTiles.Add(new List<string>(){"10111000", "40"});
		TunnelTiles.Add(new List<string>(){"10111001", "40"});
		TunnelTiles.Add(new List<string>(){"10111010", "42"});
		TunnelTiles.Add(new List<string>(){"10111011", "42"});
		TunnelTiles.Add(new List<string>(){"10111100", "40"});
		TunnelTiles.Add(new List<string>(){"10111101", "40"});
		TunnelTiles.Add(new List<string>(){"10111110", "42"});
		TunnelTiles.Add(new List<string>(){"10111111", "42"});
		TunnelTiles.Add(new List<string>(){"11000000", "18"});
		TunnelTiles.Add(new List<string>(){"11000001", "23"});
		TunnelTiles.Add(new List<string>(){"11000010", "41"});
		TunnelTiles.Add(new List<string>(){"11000011", "41"});
		TunnelTiles.Add(new List<string>(){"11000100", "24"});
		TunnelTiles.Add(new List<string>(){"11000101", "34"});
		TunnelTiles.Add(new List<string>(){"11000110", "41"});
		TunnelTiles.Add(new List<string>(){"11000111", "41"});
		TunnelTiles.Add(new List<string>(){"11001000", "31"});
		TunnelTiles.Add(new List<string>(){"11001001", "31"});
		TunnelTiles.Add(new List<string>(){"11001010", "43"});
		TunnelTiles.Add(new List<string>(){"11001011", "43"});
		TunnelTiles.Add(new List<string>(){"11001100", "38"});
		TunnelTiles.Add(new List<string>(){"11001101", "38"});
		TunnelTiles.Add(new List<string>(){"11001110", "43"});
		TunnelTiles.Add(new List<string>(){"11001111", "43"});
		TunnelTiles.Add(new List<string>(){"11010000", "30"});
		TunnelTiles.Add(new List<string>(){"11010001", "39"});
		TunnelTiles.Add(new List<string>(){"11010010", "44"});
		TunnelTiles.Add(new List<string>(){"11010011", "44"});
		TunnelTiles.Add(new List<string>(){"11010100", "30"});
		TunnelTiles.Add(new List<string>(){"11010101", "39"});
		TunnelTiles.Add(new List<string>(){"11010110", "44"});
		TunnelTiles.Add(new List<string>(){"11010111", "44"});
		TunnelTiles.Add(new List<string>(){"11011000", "45"});
		TunnelTiles.Add(new List<string>(){"11011001", "45"});
		TunnelTiles.Add(new List<string>(){"11011010", "46"});
		TunnelTiles.Add(new List<string>(){"11011011", "46"});
		TunnelTiles.Add(new List<string>(){"11011100", "45"});
		TunnelTiles.Add(new List<string>(){"11011101", "45"});
		TunnelTiles.Add(new List<string>(){"11011110", "46"});
		TunnelTiles.Add(new List<string>(){"11011111", "46"});
		TunnelTiles.Add(new List<string>(){"11100000", "18"});
		TunnelTiles.Add(new List<string>(){"11100001", "23"});
		TunnelTiles.Add(new List<string>(){"11100010", "41"});
		TunnelTiles.Add(new List<string>(){"11100011", "41"});
		TunnelTiles.Add(new List<string>(){"11100100", "24"});
		TunnelTiles.Add(new List<string>(){"11100101", "34"});
		TunnelTiles.Add(new List<string>(){"11100110", "41"});
		TunnelTiles.Add(new List<string>(){"11100111", "41"});
		TunnelTiles.Add(new List<string>(){"11101000", "31"});
		TunnelTiles.Add(new List<string>(){"11101001", "31"});
		TunnelTiles.Add(new List<string>(){"11101010", "43"});
		TunnelTiles.Add(new List<string>(){"11101011", "43"});
		TunnelTiles.Add(new List<string>(){"11101100", "38"});
		TunnelTiles.Add(new List<string>(){"11101101", "38"});
		TunnelTiles.Add(new List<string>(){"11101110", "43"});
		TunnelTiles.Add(new List<string>(){"11101111", "43"});
		TunnelTiles.Add(new List<string>(){"11110000", "30"});
		TunnelTiles.Add(new List<string>(){"11110001", "39"});
		TunnelTiles.Add(new List<string>(){"11110010", "44"});
		TunnelTiles.Add(new List<string>(){"11110011", "44"});
		TunnelTiles.Add(new List<string>(){"11110100", "30"});
		TunnelTiles.Add(new List<string>(){"11110101", "39"});
		TunnelTiles.Add(new List<string>(){"11110110", "44"});
		TunnelTiles.Add(new List<string>(){"11110111", "44"});
		TunnelTiles.Add(new List<string>(){"11111000", "45"});
		TunnelTiles.Add(new List<string>(){"11111001", "45"});
		TunnelTiles.Add(new List<string>(){"11111010", "46"});
		TunnelTiles.Add(new List<string>(){"11111011", "46"});
		TunnelTiles.Add(new List<string>(){"11111100", "45"});
		TunnelTiles.Add(new List<string>(){"11111101", "45"});
		TunnelTiles.Add(new List<string>(){"11111110", "46"});
		TunnelTiles.Add(new List<string>(){"11111111", "46"});
		changeDisplayFromIndex();
    }

    // Update is called once per frame
    void Update()
    {
        if(Input.GetMouseButtonDown(0)){
			current_index += 1;
			print(current_index + " / 253");
			changeDisplayFromIndex();
			// Whatever you want it to do.
		}
        else if(Input.GetMouseButtonDown(1)){
			current_index -= 1;
			print(current_index + " / 253");
			changeDisplayFromIndex();
			// Whatever you want it to do.
		}
    }
	
	public void changeDisplayFromIndex(){
		List<string> setup = TunnelTiles[current_index];
		current_string_1 = setup[0];
		current_string_2 = setup[1];
		Texture2D texture = Resources.Load<Texture2D>("Blocks/DirtConnectors/" + current_string_2) as Texture2D;
		main.GetComponent<SpriteRenderer>().sprite = Sprite.Create(
			texture,
			new Rect(0, 0, 50, 50), // section of texture to use
			new Vector2(0.5f, 0.5f), // pivot in centre
			50 // pixels per unity tile grid unit
		);
		if(current_string_1[0] == '1'){
			texture = Resources.Load<Texture2D>("Blocks/Dirt1") as Texture2D;
			b0.GetComponent<SpriteRenderer>().sprite = Sprite.Create(
				texture,
				new Rect(0, 0, 50, 50), // section of texture to use
				new Vector2(0.5f, 0.5f), // pivot in centre
				50 // pixels per unity tile grid unit
			);
		}
		else{
			texture = Resources.Load<Texture2D>("Blocks/Blank") as Texture2D;
			b0.GetComponent<SpriteRenderer>().sprite = Sprite.Create(
				texture,
				new Rect(0, 0, 50, 50), // section of texture to use
				new Vector2(0.5f, 0.5f), // pivot in centre
				50 // pixels per unity tile grid unit
			);			
		}
		if(current_string_1[1] == '1'){
			texture = Resources.Load<Texture2D>("Blocks/Dirt1") as Texture2D;
			b1.GetComponent<SpriteRenderer>().sprite = Sprite.Create(
				texture,
				new Rect(0, 0, 50, 50), // section of texture to use
				new Vector2(0.5f, 0.5f), // pivot in centre
				50 // pixels per unity tile grid unit
			);
		}
		else{
			texture = Resources.Load<Texture2D>("Blocks/Blank") as Texture2D;
			b1.GetComponent<SpriteRenderer>().sprite = Sprite.Create(
				texture,
				new Rect(0, 0, 50, 50), // section of texture to use
				new Vector2(0.5f, 0.5f), // pivot in centre
				50 // pixels per unity tile grid unit
			);			
		}
		if(current_string_1[2] == '1'){
			texture = Resources.Load<Texture2D>("Blocks/Dirt1") as Texture2D;
			b2.GetComponent<SpriteRenderer>().sprite = Sprite.Create(
				texture,
				new Rect(0, 0, 50, 50), // section of texture to use
				new Vector2(0.5f, 0.5f), // pivot in centre
				50 // pixels per unity tile grid unit
			);
		}
		else{
			texture = Resources.Load<Texture2D>("Blocks/Blank") as Texture2D;
			b2.GetComponent<SpriteRenderer>().sprite = Sprite.Create(
				texture,
				new Rect(0, 0, 50, 50), // section of texture to use
				new Vector2(0.5f, 0.5f), // pivot in centre
				50 // pixels per unity tile grid unit
			);			
		}
		if(current_string_1[3] == '1'){
			texture = Resources.Load<Texture2D>("Blocks/Dirt1") as Texture2D;
			b3.GetComponent<SpriteRenderer>().sprite = Sprite.Create(
				texture,
				new Rect(0, 0, 50, 50), // section of texture to use
				new Vector2(0.5f, 0.5f), // pivot in centre
				50 // pixels per unity tile grid unit
			);
		}
		else{
			texture = Resources.Load<Texture2D>("Blocks/Blank") as Texture2D;
			b3.GetComponent<SpriteRenderer>().sprite = Sprite.Create(
				texture,
				new Rect(0, 0, 50, 50), // section of texture to use
				new Vector2(0.5f, 0.5f), // pivot in centre
				50 // pixels per unity tile grid unit
			);			
		}
		if(current_string_1[4] == '1'){
			texture = Resources.Load<Texture2D>("Blocks/Dirt1") as Texture2D;
			b4.GetComponent<SpriteRenderer>().sprite = Sprite.Create(
				texture,
				new Rect(0, 0, 50, 50), // section of texture to use
				new Vector2(0.5f, 0.5f), // pivot in centre
				50 // pixels per unity tile grid unit
			);
		}
		else{
			texture = Resources.Load<Texture2D>("Blocks/Blank") as Texture2D;
			b4.GetComponent<SpriteRenderer>().sprite = Sprite.Create(
				texture,
				new Rect(0, 0, 50, 50), // section of texture to use
				new Vector2(0.5f, 0.5f), // pivot in centre
				50 // pixels per unity tile grid unit
			);			
		}
		if(current_string_1[5] == '1'){
			texture = Resources.Load<Texture2D>("Blocks/Dirt1") as Texture2D;
			b5.GetComponent<SpriteRenderer>().sprite = Sprite.Create(
				texture,
				new Rect(0, 0, 50, 50), // section of texture to use
				new Vector2(0.5f, 0.5f), // pivot in centre
				50 // pixels per unity tile grid unit
			);
		}
		else{
			texture = Resources.Load<Texture2D>("Blocks/Blank") as Texture2D;
			b5.GetComponent<SpriteRenderer>().sprite = Sprite.Create(
				texture,
				new Rect(0, 0, 50, 50), // section of texture to use
				new Vector2(0.5f, 0.5f), // pivot in centre
				50 // pixels per unity tile grid unit
			);			
		}
		if(current_string_1[6] == '1'){
			texture = Resources.Load<Texture2D>("Blocks/Dirt1") as Texture2D;
			b6.GetComponent<SpriteRenderer>().sprite = Sprite.Create(
				texture,
				new Rect(0, 0, 50, 50), // section of texture to use
				new Vector2(0.5f, 0.5f), // pivot in centre
				50 // pixels per unity tile grid unit
			);
		}
		else{
			texture = Resources.Load<Texture2D>("Blocks/Blank") as Texture2D;
			b6.GetComponent<SpriteRenderer>().sprite = Sprite.Create(
				texture,
				new Rect(0, 0, 50, 50), // section of texture to use
				new Vector2(0.5f, 0.5f), // pivot in centre
				50 // pixels per unity tile grid unit
			);			
		}
		if(current_string_1[7] == '1'){
			texture = Resources.Load<Texture2D>("Blocks/Dirt1") as Texture2D;
			b7.GetComponent<SpriteRenderer>().sprite = Sprite.Create(
				texture,
				new Rect(0, 0, 50, 50), // section of texture to use
				new Vector2(0.5f, 0.5f), // pivot in centre
				50 // pixels per unity tile grid unit
			);
		}
		else{
			texture = Resources.Load<Texture2D>("Blocks/Blank") as Texture2D;
			b7.GetComponent<SpriteRenderer>().sprite = Sprite.Create(
				texture,
				new Rect(0, 0, 50, 50), // section of texture to use
				new Vector2(0.5f, 0.5f), // pivot in centre
				50 // pixels per unity tile grid unit
			);			
		}
	}
}
