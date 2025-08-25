using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using TMPro;
using UnityEngine.SceneManagement;

public class UIManager : MonoBehaviour
{
	public GameObject player;
	public GameObject[] allUI;
	public GameObject[] freezingMoneyUI;
	public GameObject MoneyUI;
	public GameObject FuelUI;
	public GameObject HullUI;
	public GameObject DepthUI;
	public int displayed_money;
	public int previous_fuel_percent;
	private bool is_low_fuel_playing;
	public GameObject low_fuel_text;
	private bool is_very_low_fuel_playing;
	public GameObject very_low_fuel_text;
	public int previous_hull_percent;
	private List<Sprite> fuel_sprites;
	private List<Sprite> hull_sprites;
	
	void Start(){
		fuel_sprites = new List<Sprite>();
		for(int i = 100; i >= 0; i--){ //This is in reverse because fuel sprites are in reverse order
			Texture2D texture = Resources.Load<Texture2D>("UI/HUD/FuelSprite/" + i) as Texture2D;
			fuel_sprites.Add(Sprite.Create(
				texture,
				new Rect(0, 0, texture.width, texture.height), // section of texture to use
				new Vector2(0.5f, 0.5f) // pivot in centre
			));
		}
		hull_sprites =  new List<Sprite>();
		for(int i = 20; i >= 0; i--){ //This is in reverse because fuel sprites are in reverse order
			Texture2D texture = Resources.Load<Texture2D>("UI/HUD/HullSprite/" + i) as Texture2D;
			hull_sprites.Add(Sprite.Create(
				texture,
				new Rect(0, 0, texture.width, texture.height), // section of texture to use
				new Vector2(0.5f, 0.5f) // pivot in centre
			));
		}
		updateFuelUI();
		updateHullUI();
	}
	
	void Update(){
		updateDepthUI(); //Needs to be updated every frame
		if(displayed_money != LevelData.player_money && !isFreezingMoneyUIOpen()){
			displayed_money = (int) Mathf.MoveTowards((float) displayed_money, (float) LevelData.player_money, Mathf.Max(1, Mathf.Abs((LevelData.player_money-displayed_money)/20)));
			updateMoneyUI();
		}
	}
		
	public void updateAllUI(){
		updateMoneyUI();
		updateFuelUI();
		updateHullUI();
		updateDepthUI();
	}
	
	public void updateMoneyUI(){
		MoneyUI.GetComponent<TextMeshProUGUI>().SetText("$" + displayed_money.ToString("n0", LevelData.string_format));
	}
	
	public void updateFuelUI(){
		int percent_fuel_value = (int) Mathf.Ceil((LevelData.player_fuel/LevelData.player_max_fuel) * 100);
		percent_fuel_value = Mathf.Max(percent_fuel_value, 0);
		if (percent_fuel_value != previous_fuel_percent){
			previous_fuel_percent = percent_fuel_value;
			FuelUI.GetComponent<Image>().overrideSprite = fuel_sprites[percent_fuel_value];
			if(percent_fuel_value > 20){
				if(is_low_fuel_playing){
					FindObjectOfType<AudioManager>().StopSound("LowFuelWarning");
					low_fuel_text.SetActive(false);
					is_low_fuel_playing = false;
				}
				if(is_very_low_fuel_playing){
					FindObjectOfType<AudioManager>().StopSound("VeryLowFuelWarning");
					very_low_fuel_text.SetActive(false);
					is_very_low_fuel_playing = false;
				}
			}
			else if(percent_fuel_value <= 20 && percent_fuel_value > 7){
				if(!is_low_fuel_playing){
					FindObjectOfType<AudioManager>().PlaySound("LowFuelWarning");
					low_fuel_text.SetActive(true);
					is_low_fuel_playing = true;
				}
				if(is_very_low_fuel_playing){
					FindObjectOfType<AudioManager>().StopSound("VeryLowFuelWarning");
					very_low_fuel_text.SetActive(false);
					is_very_low_fuel_playing = false;
				}
			}
			else if(percent_fuel_value <= 7){
				if(is_low_fuel_playing){
					FindObjectOfType<AudioManager>().StopSound("LowFuelWarning");
					low_fuel_text.SetActive(false);
					is_low_fuel_playing = false;
				}
				if(!is_very_low_fuel_playing){
					FindObjectOfType<AudioManager>().PlaySound("VeryLowFuelWarning");
					very_low_fuel_text.SetActive(true);
					is_very_low_fuel_playing = true;
				}
			}
		}
	}

	public void updateHullUI(){
		int percent_hull_value = (int) Mathf.Ceil(((float) LevelData.player_hp/(float) LevelData.player_max_hp) * 20); //Because my sprites only go from 0 to 20
		percent_hull_value = Mathf.Max(percent_hull_value, 0);
		if (percent_hull_value != previous_hull_percent){
			previous_hull_percent = percent_hull_value;
			HullUI.GetComponent<Image>().overrideSprite = hull_sprites[percent_hull_value];
		}
	}

	public void updateDepthUI(){
		if(player){
			float depth = Mathf.Floor((player.transform.position.y + 3.5f)*12.5f);
			if (depth > -5800f)
				DepthUI.GetComponent<TextMeshProUGUI>().SetText(depth + " ft.");
			else if (depth > -7300f)
				DepthUI.GetComponent<TextMeshProUGUI>().SetText("?" + Random.Range(10000, 99999) + " ft.");
			else
				DepthUI.GetComponent<TextMeshProUGUI>().SetText("-66666 ft.");
		}
	}
	
	public bool isUIOpen(){
		foreach(GameObject ui in allUI){
			if(ui.activeSelf){
				return true;
			}
		}
		return false;
	}
	
	public bool isFreezingMoneyUIOpen(){
		foreach(GameObject ui in freezingMoneyUI){
			if(ui.activeSelf){
				return true;
			}
		}
		return false;
	}

	public void returnToMainMenu(){
		Time.timeScale = 1f;
		FindObjectOfType<AudioManager>().StopAllMusic();
		FindObjectOfType<AudioManager>().StopAllSounds();
		SceneManager.LoadScene("MainMenu");
	}
}
