using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TMPro;

public class MineralBuyerManager : MonoBehaviour
{
	public GameObject player;
	public GameObject sell_mineral_grid_layout;
	public GameObject ui_manager_gameobject;
	private UIManager ui_manager;
	public GameObject popup_manager_gameobject;
	private PopupManager popup_manager;
	private AudioManager audio_manager;

    void OnEnable(){
		player.GetComponent<PlayerMovement>().enterShop();
		setManagers();
        updateDisplay();
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
		
	private void setManagers(){
		ui_manager = ui_manager_gameobject.GetComponent<UIManager>();
		popup_manager = popup_manager_gameobject.GetComponent<PopupManager>();
	}
	
	public void closeUI(){
		gameObject.SetActive(false);
		audio_manager.PlayMusic("MainLevelMusic");
		LevelData.saveData();
	}
	
	private void updateDisplay(){
		int total = 0;
		for(int i = 0; i < sell_mineral_grid_layout.transform.childCount; i++){
			GameObject line = sell_mineral_grid_layout.transform.GetChild(i).gameObject;
			if(line.name != "SeparatorLine" && line.name != "SellAllButton" && LevelData.player_cargo[line.name] > 0){
				activateLine(line);
				int quantity = LevelData.player_cargo[line.name];
				int ore_value = LevelData.minerals[line.name].ore_value;
				int ore_total = ore_value * quantity;
				line.transform.Find("Quantity").GetComponent<TextMeshProUGUI>().text = quantity.ToString();
				line.transform.Find("Value").GetComponent<TextMeshProUGUI>().text = "$" + ore_value.ToString("n0", LevelData.string_format);
				line.transform.Find("TotalValue").GetComponent<TextMeshProUGUI>().text = "$" + ore_total.ToString("n0", LevelData.string_format);
				total += ore_total;
			}
			else if (line.name != "SeparatorLine" && line.name != "SellAllButton"){
				deactivateLine(line);
			}
		}
		sell_mineral_grid_layout.transform.Find("SellAllButton/TotalValue").GetComponent<TextMeshProUGUI>().text = "$" + total.ToString("n0", LevelData.string_format);
	}
	
	private void activateLine(GameObject line){
		for(int i = 0; i < line.transform.childCount; i++){
			line.transform.GetChild(i).gameObject.SetActive(true);
		}
	}

	private void deactivateLine(GameObject line){
		for(int i = 0; i < line.transform.childCount; i++){
			line.transform.GetChild(i).gameObject.SetActive(false);
		}
	}
	
	public void sellAllMinerals(){
		int total = LevelData.sellCargo();
		ui_manager.updateMoneyUI();
		updateDisplay();
		popup_manager.openPopup("Sold all minerals for $" + total);
		ui_manager.updateMoneyUI();
		audio_manager.PlaySoundOneShot("SellMinerals");
	}
}
