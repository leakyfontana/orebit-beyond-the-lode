using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.SceneManagement;

public class MainMenuManager : MonoBehaviour
{
	public GameObject helpUI;
	public GameObject popup;
	
    // Start is called before the first frame update
    void Start()
    {
        
    }

    // Update is called once per frame
    void Update()
    {
        
    }
	
	public void startNewGame(){
		if(!helpUI.activeSelf){
			FindObjectOfType<AudioManager>().PlaySoundOneShot("SelectUpgradeCategory");
			LevelData.setNewGameData();
			SceneManager.LoadScene("Game");
		}
	}
	
	public void continueGame(){
		if(!helpUI.activeSelf){
			if(LevelData.doesSaveFileExist()){
				FindObjectOfType<AudioManager>().PlaySoundOneShot("SelectUpgradeCategory");
				LevelData.loadData();
				SceneManager.LoadScene("Game");
			}
			else {
				popup.GetComponent<PopupManager>().openPopupWithoutSlowTextDisplayer("No save game present on disk!");
			}
		}		
	}
	
	public void openInstructions(){
		FindObjectOfType<AudioManager>().PlaySoundOneShot("SelectUpgradeCategory");
		helpUI.SetActive(true);
	}

	public void closeInstructions(){
		FindObjectOfType<AudioManager>().PlaySoundOneShot("SelectUpgradeCategory");
		helpUI.SetActive(false);
	}
}
