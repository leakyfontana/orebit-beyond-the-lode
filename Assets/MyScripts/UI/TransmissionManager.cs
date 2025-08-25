using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class TransmissionManager : MonoBehaviour
{
	public GameObject player;
	public GameObject text_area;
	public GameObject portrait_miner;
	public GameObject portrait_natas;
	public GameObject portrait_static;
	private int current_transmission_index;
    // Start is called before the first frame update
    void Start()
    {
        
    }

    // Update is called once per frame
    void Update()
    {
        if (Input.GetKeyDown(KeyCode.Escape)){
            closeUI();
        }
    }
	
	public void openUI(){
		player.GetComponent<PlayerMovement>().enterShop();
		gameObject.SetActive(true);
	}
	
	public void closeUI(){
		if(current_transmission_index == 1){
			player.GetComponent<PlayerMovement>().createPopup("Bonus\n+$1000", "IsMineral");
			LevelData.player_money += 1000;
			GameObject.FindWithTag("AudioManager").GetComponent<AudioManager>().PlaySoundOneShot("Purchase");
		}
		else if(current_transmission_index == 2){
			player.GetComponent<PlayerMovement>().createPopup("Bonus\n+$3000", "IsMineral");
			LevelData.player_money += 3000;				
			GameObject.FindWithTag("AudioManager").GetComponent<AudioManager>().PlaySoundOneShot("Purchase");
		}
		else if(current_transmission_index == 7){
			player.GetComponent<PlayerMovement>().createPopup("Bonus\n+$25000", "IsMineral");
			LevelData.player_money += 25000;
			GameObject.FindWithTag("AudioManager").GetComponent<AudioManager>().PlaySoundOneShot("Purchase");
		}
		current_transmission_index = 0;
		player.GetComponent<PlayerMovement>().exitShop();
		gameObject.SetActive(false);
	}
	
	public void displayTransmission(int transmission_index){
		if (!LevelData.transmissions[transmission_index].displayed){
			(string text, string signature, string picture_name, bool displayed) trans = LevelData.transmissions[transmission_index];
			current_transmission_index = transmission_index;
			updateText(trans.text, trans.signature);
			updatePortrait(trans.picture_name);
			LevelData.transmissions[transmission_index] = (trans.text, trans.signature, trans.picture_name, true);
			openUI();
			GameObject.FindWithTag("AudioManager").GetComponent<AudioManager>().PlaySoundOneShot("Transmission");
		}
	}
	
	public void updateText(string text, string signature){
		string display_text = "** Transmission Received **\n'" + signature + "'\n\n";
		display_text += text;
		display_text += "\n\n** Transmission Terminated **";
		text_area.GetComponent<SlowTextDisplayer>().setText(display_text);
	}
	
	public void updatePortrait(string name){
		if(name == "miner"){
			portrait_miner.SetActive(true);
			portrait_natas.SetActive(false);
			portrait_static.SetActive(false);
		}
		if(name == "natas"){
			portrait_miner.SetActive(false);
			portrait_natas.SetActive(true);
			portrait_static.SetActive(false);
		}
		if(name == "static"){
			portrait_miner.SetActive(false);
			portrait_natas.SetActive(false);
			portrait_static.SetActive(true);
		}
		
	}
}
