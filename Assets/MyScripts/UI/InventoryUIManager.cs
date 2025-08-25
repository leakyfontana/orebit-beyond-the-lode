using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using TMPro;

public class InventoryUIManager : MonoBehaviour
{
	public GameObject player;
	public GameObject audio_manager;
	public GameObject ui_manager;
	public GameObject cargo_text;
	public GameObject equipment;
	public GameObject minerals_list;
	// Update is called once per frame
    void Update()
    {
        if (Input.GetKeyDown(KeyCode.Escape)){
            closeUI();
        }
    }
	
	public void openUI(){
		if(player.activeSelf && !ui_manager.GetComponent<UIManager>().isUIOpen()){
			player.GetComponent<PlayerMovement>().enterShop();
			updateAll();
			gameObject.SetActive(true);			
		}
	}
	
	private void updateAll(){
		updateCargo();
		updateUpgrades();
		updateItems();
		updateMinerals();
	}
	
	private void updateCargo(){
		print((float) LevelData.player_current_cargo_weight);
		print((float) LevelData.player_max_cargo_weight);
		cargo_text.GetComponent<TextMeshProUGUI>().text = "Cargo " + Mathf.Round(((float) LevelData.player_current_cargo_weight / (float) LevelData.player_max_cargo_weight) * 100) + "% full\n" + LevelData.player_total_weight.ToString() + " Kg";		
	}
	
	private void updateUpgrades(){
		foreach(KeyValuePair<string, string> upgrade in LevelData.current_upgrades){
			equipment.transform.Find(upgrade.Key).GetComponent<TextMeshProUGUI>().text = upgrade.Value;
		}
	}
	
	private void updateItems(){
		foreach(KeyValuePair<string, int> item in LevelData.player_items){
			print(item.Key);
			GameObject item_picture = equipment.transform.Find(item.Key).gameObject;
			Color color = item_picture.GetComponent<Image>().color;
			if(item.Value <= 0){
				color.a = 0.25f;
				item_picture.transform.Find("Quantity").GetComponent<TextMeshProUGUI>().text = "";
			}
			else{
				color.a = 1f;
				item_picture.transform.Find("Quantity").GetComponent<TextMeshProUGUI>().text = "x" + item.Value;
			}
			item_picture.GetComponent<Image>().color = color;
		}
	}

	private void updateMinerals(){
		foreach(KeyValuePair<string, int> mineral in LevelData.player_cargo){
			GameObject mineral_line = minerals_list.transform.Find(mineral.Key).gameObject;
			Color color = mineral_line.transform.Find("Image").GetComponent<Image>().color;
			if(mineral.Value <= 0){
				color.a = 0.25f;
				mineral_line.transform.Find("Quantity").GetComponent<TextMeshProUGUI>().text = "";
				mineral_line.transform.Find("Name").GetComponent<TextMeshProUGUI>().text = "";
				mineral_line.transform.Find("Image/DropButton").gameObject.SetActive(false);
			}
			else{
				color.a = 1f;
				mineral_line.transform.Find("Quantity").GetComponent<TextMeshProUGUI>().text = "x" + mineral.Value;
				mineral_line.transform.Find("Name").GetComponent<TextMeshProUGUI>().text = mineral.Key;
				mineral_line.transform.Find("Image/DropButton").gameObject.SetActive(true);
			}
			mineral_line.transform.Find("Image").GetComponent<Image>().color = color;
		}
	}

	public void closeUI(){
		player.GetComponent<PlayerMovement>().exitShop();
		gameObject.SetActive(false);
	}
	
	public void dropMineral(string name){
		LevelData.removeMineralInCargo(name);
		FindObjectOfType<AudioManager>().GetComponent<AudioManager>().PlaySoundOneShot("JettisonMineral");
		updateAll();
	}
}
