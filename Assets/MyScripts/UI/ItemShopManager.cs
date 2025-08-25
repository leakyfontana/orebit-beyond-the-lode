using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TMPro;
using UnityEngine.UI;

public class ItemShopManager : MonoBehaviour
{
	public GameObject player;
	public GameObject ui_manager_gameobject;
	private UIManager ui_manager;
	public GameObject popup_manager_gameobject;
	private PopupManager popup_manager;
	private AudioManager audio_manager;
	
	public GameObject item_name_text;
	public GameObject item_price_text;
	public GameObject item_description_text;
	private string currently_selected_item;
	public GameObject[] item_counter_object_list;
	public GameObject hull_display_bar;
	public GameObject hull_display_text;
	
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
	
    void Update()
    {
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
	
	public void openDisplay(){
		item_name_text.GetComponent<SlowTextDisplayer>().setText("");
		item_price_text.GetComponent<SlowTextDisplayer>().setText("");
		item_description_text.GetComponent<SlowTextDisplayer>().setText("");
		updateDisplay();
	}
	
	private void updateDisplay(){
		updateHullBarDisplay();
		updateItemCountDisplay();
	}
	
	public void updateHullBarDisplay(){
		hull_display_bar.GetComponent<Slider>().value = (float) LevelData.player_hp / LevelData.player_max_hp;
		hull_display_text.GetComponent<TextMeshProUGUI>().text = LevelData.player_hp + "/" + LevelData.player_max_hp + " HP";		
	}
	
	private void updateItemCountDisplay(){
		foreach(GameObject obj in item_counter_object_list){
			obj.GetComponent<TextMeshProUGUI>().text = "x" + LevelData.player_items[obj.name];
		}
	}

	public void updateItemInformationScreen(string name){
		Debug.Log("Updating display for: " + name);
		currently_selected_item = name;
		(int price, string description, string button_to_press) item_data = LevelData.items[name]; 
		item_name_text.GetComponent<SlowTextDisplayer>().setText(name);
		item_price_text.GetComponent<SlowTextDisplayer>().setText("$" + item_data.price.ToString("n0", LevelData.string_format) + "   (Press '" + item_data.button_to_press + "' to use)");
		item_description_text.GetComponent<SlowTextDisplayer>().setText(item_data.description);
		audio_manager.PlaySoundOneShot("SelectUpgrade");
	}
	
	public void buyItem(){
		Debug.Log("Buying item: " + currently_selected_item);
		int price = LevelData.items[currently_selected_item].price;
		if(LevelData.tryToBuy(price)){
			LevelData.addItem(currently_selected_item);
			audio_manager.PlaySoundOneShot("Purchase");
		}
		else{
			popup_manager.openPopup("You need $" + price + " to purchase");
			audio_manager.PlaySoundOneShot("Error2");
		}
		ui_manager.updateMoneyUI();
		updateDisplay();
	}
	
	public void addHull(int dollar_amount){ //Fifteen dollar = 1 HP
		Debug.Log("Adding " + dollar_amount + " hull");
		if(LevelData.player_hp == LevelData.player_max_hp){
			popup_manager.openPopup("No damage to repair!");
			audio_manager.PlaySoundOneShot("Error2");
		}
		else if(LevelData.tryToBuy(dollar_amount)){
			LevelData.addHull(dollar_amount);
			audio_manager.PlaySoundOneShot("Purchase");
		}
		else{
			popup_manager.openPopup("You need $" + dollar_amount + " to purchase");
			audio_manager.PlaySoundOneShot("Error2");

		}
		ui_manager.updateMoneyUI();
		ui_manager.updateHullUI();
		updateDisplay();
	}
	
	public void fillHull(){
		int required_amount = (LevelData.player_max_hp - LevelData.player_hp) * 15; //15 dollar = 1 HP
		addHull(required_amount);
	}
}
