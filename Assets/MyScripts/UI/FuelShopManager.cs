using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TMPro;
using UnityEngine.UI;

public class FuelShopManager : MonoBehaviour
{
	public GameObject player;
	public GameObject ui_manager_gameobject;
	private UIManager ui_manager;
	public GameObject popup_manager_gameobject;
	private AudioManager audio_manager;
	
	private PopupManager popup_manager;
	public GameObject fuel_display_bar;
	public GameObject fuel_display_text;
	

    void OnEnable(){
		player.GetComponent<PlayerMovement>().enterShop();
		setManagers();
        updateFuelBarDisplay();
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
		gameObject.SetActive(false);
		audio_manager.PlayMusic("MainLevelMusic");
		LevelData.saveData();
	}
	
	private void setManagers(){
		ui_manager = ui_manager_gameobject.GetComponent<UIManager>();
		popup_manager = popup_manager_gameobject.GetComponent<PopupManager>();
	}
	
	private void updateFuelBarDisplay(){
		fuel_display_bar.GetComponent<Slider>().value = LevelData.player_fuel / LevelData.player_max_fuel;
		fuel_display_text.GetComponent<TextMeshProUGUI>().text = (int) LevelData.player_fuel + "/" + (int) LevelData.player_max_fuel + " L";
	}
	
	public void addFuel(int dollar_amount){ //One dollar = one fuel
		Debug.Log("Adding " + dollar_amount + " fuel");
		if(LevelData.player_fuel == LevelData.player_max_fuel){
			popup_manager.openPopup("Tank is full!");
			audio_manager.PlaySoundOneShot("Error2");
		}
		else if(LevelData.tryToBuy(dollar_amount)){
			LevelData.addFuel(dollar_amount);
			audio_manager.PlaySoundOneShot("Purchase");
		}
		else{
			popup_manager.openPopup("You need $" + dollar_amount + " to purchase");
			audio_manager.PlaySoundOneShot("Error2");
		}
		ui_manager.updateMoneyUI();
		ui_manager.updateFuelUI();
		updateFuelBarDisplay();
	}
	
	public void fillFuel(){
		int required_amount = (int) Mathf.Ceil(LevelData.player_max_fuel - LevelData.player_fuel);
		addFuel(required_amount);
	}
}
