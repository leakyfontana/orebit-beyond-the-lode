using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TMPro;
using UnityEngine.UI;

public class UpgradeShopUI : MonoBehaviour
{
	public GameObject player;
	public GameObject ui_manager_gameobject;
	private UIManager ui_manager;
	public GameObject popup_manager_gameobject;
	private PopupManager popup_manager;
	private AudioManager audio_manager;
	
	public GameObject welcome_ui;
	public GameObject upgrade_grid_display;
	public GameObject upgrade_grid_area;
	public GameObject upgrade_display;
	
	private string current_category;
	public GameObject current_category_display;
	public GameObject current_upgrade_display;
	public GameObject current_upgrade_name;
	
	public GameObject potential_upgrade_name;
	public GameObject potential_upgrade_price;
	public GameObject potential_upgrade_effect;
	private string current_potential_upgrade;
	public GameObject[] potential_upgrade_pictures;
	
	private Dictionary<string, string[]> upgrades = new Dictionary<string, string[]>(){
		{"Drill", new string [] {"Stock Drill", "Silvide Drill", "Goldium Drill", "Emerald Drill", "Ruby Drill", "Diamond Drill", "Amazonite Drill"}},
		{"Hull", new string[] {"Stock Hull", "Ironium Hull", "Bronzium Hull", "Steel Hull", "Platinium Hull", "Einsteinium Hull", "Energy-Shielded Hull"}},
		{"Engine", new string[] {"Stock Engine", "V4 1600 cc", "V4 2.0 Ltr Turbo", "V6 3.8 Ltr", "V8 Supercharged 5.0 Ltr", "V12 6.0 Ltr", "V16 Jag Engine"}},
		{"Fuel", new string[] {"Micro Tank", "Medium Tank", "Huge Tank" , "Gigantic Tank", "Titanic Tank", "Leviathan Tank", "Liquid Compression Tank"}},
		{"Radiator", new string[] {"Stock Fan", "Dual Fans", "Single Turbine", "Dual Turbines", "Puron Cooling", "Tri-Turbine Freon Array"}},
		{"Cargo", new string[] {"Micro Bay", "Medium Bay", "Huge Bay", "Gigantic Bay", "Titanic Bay", "Leviathan Bay"}},
	};
	
	private Dictionary<string, (string unit, int multiplier)> effect_from_category = new Dictionary<string, (string, int)>(){
		{"Drill", (" Ft/s", 10)},
		{"Hull", (" Health", 1)},
		{"Engine", (" HorsePower", 25)},
		{"Fuel", (" Liters", 1)},
		{"Radiator", ("% Effective", 100)},
		{"Cargo", (" Cu ft.", 1)},
	};
	
	void OnEnable(){
		player.GetComponent<PlayerMovement>().enterShop();
		setManagers();
        openDisplay();
    }
	
	void OnDisable(){
		player.GetComponent<PlayerMovement>().exitShop();
		ui_manager.updateAllUI();
	}
	
	void Start(){
		audio_manager = FindObjectOfType<AudioManager>();
	}
	
	void Update(){
		if (Input.GetKeyDown(KeyCode.Escape)){
            closeUI();
        }
    }
		
	public void closeUI(){
		current_category = "";
		current_potential_upgrade = "";
		gameObject.SetActive(false);
		audio_manager.PlayMusic("MainLevelMusic");
		LevelData.saveData();
	}
	
	private void setManagers(){
		ui_manager = ui_manager_gameobject.GetComponent<UIManager>();
		popup_manager = popup_manager_gameobject.GetComponent<PopupManager>();
	}
	
	public void openDisplay(){
		welcome_ui.SetActive(true);
		upgrade_display.SetActive(false);
		upgrade_grid_area.SetActive(false);
		current_category = "";
		current_potential_upgrade = "";
		current_category_display.GetComponent<TextMeshProUGUI>().text = current_category;
		potential_upgrade_name.GetComponent<SlowTextDisplayer>().setText(current_potential_upgrade);
	}

	public void setImage(Image image, string path_to_texture){
		Texture2D texture = Resources.Load<Texture2D>(path_to_texture) as Texture2D;
		image.sprite = Sprite.Create(
			texture,
			new Rect(0, 0, 80, 80), // section of texture to use
			new Vector2(0.5f, 0.5f) // pivot in centre
		);		
	}
	
	public void displayCategory(string category){
		if(category != current_category){
			current_category = category;
			updateCategory();
			audio_manager.PlaySoundOneShot("SelectUpgradeCategory");
		}
	}
	
	public void updateCategory(){
		welcome_ui.SetActive(false);
		upgrade_display.SetActive(true);
		upgrade_grid_area.SetActive(true);
		if(current_category == "Fuel"){
			current_category_display.GetComponent<TextMeshProUGUI>().text = "Fuel Tank".ToUpper();
		}
		else {
			current_category_display.GetComponent<TextMeshProUGUI>().text = current_category.ToUpper();
		}
		string path = "UI/upgradesShop/" + current_category + "/" +  LevelData.current_upgrades[current_category];
		setImage(current_upgrade_display.GetComponent<Image>(), path);
		current_upgrade_name.GetComponent<SlowTextDisplayer>().setText(LevelData.current_upgrades[current_category]);
		print(LevelData.current_upgrades[current_category]);
		print(path);
		for(int i = 0; i < potential_upgrade_pictures.Length; i++){
			if (i > upgrades[current_category].Length - 2){
				potential_upgrade_pictures[i].SetActive(false);
			}
			else{
				potential_upgrade_pictures[i].SetActive(true);
				path = "UI/upgradesShop/" + current_category + "/" +  upgrades[current_category][i + 1];
				setImage(potential_upgrade_pictures[i].GetComponent<Image>(), path);
			}
		}
		potential_upgrade_name.GetComponent<SlowTextDisplayer>().setText("");
		potential_upgrade_price.GetComponent<SlowTextDisplayer>().setText("");
		potential_upgrade_effect.GetComponent<SlowTextDisplayer>().setText("");
	}
	
	public void displayPotentialUpgrade(int upgrade_index){
		current_potential_upgrade = upgrades[current_category][upgrade_index];
		potential_upgrade_name.GetComponent<SlowTextDisplayer>().setText(current_potential_upgrade);
		potential_upgrade_price.GetComponent<SlowTextDisplayer>().setText("$" + LevelData.upgrades[current_category][current_potential_upgrade].price.ToString("n0", LevelData.string_format));
		potential_upgrade_effect.GetComponent<SlowTextDisplayer>().setText((LevelData.upgrades[current_category][current_potential_upgrade].effect * effect_from_category[current_category].multiplier).ToString() + effect_from_category[current_category].unit);		
		audio_manager.PlaySoundOneShot("SelectUpgrade");
	}
	
	public void buyUpgrade(){
		if (LevelData.upgrades[current_category][current_potential_upgrade].effect <= LevelData.upgrades[current_category][LevelData.current_upgrades[current_category]].effect){
			popup_manager.openPopup("The upgrade you are trying to buy is not better than the one you currently have.");
			audio_manager.PlaySoundOneShot("Error2");
		}
		else{
			if(LevelData.tryToBuy(LevelData.upgrades[current_category][current_potential_upgrade].price)){
				LevelData.setUpgrade(current_category, current_potential_upgrade);
				updateCategory();
				print(LevelData.returnUpgradeString());
				ui_manager.updateAllUI();
				audio_manager.PlaySoundOneShot("Purchase");
				if(current_category == "Fuel"){
					LevelData.player_fuel = LevelData.player_max_fuel;
					ui_manager.updateFuelUI();
				}
				else if(current_category == "Hull"){
					LevelData.player_hp = LevelData.player_max_hp;
					ui_manager.updateHullUI();
				}
			}
			else{
				popup_manager.openPopup("You need $" + LevelData.upgrades[current_category][current_potential_upgrade].price + " to purchase");
				audio_manager.PlaySoundOneShot("Error2");
			}
		}
		ui_manager.updateMoneyUI();
	}
}
