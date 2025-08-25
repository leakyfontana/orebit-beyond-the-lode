using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class HelpUUIManager : MonoBehaviour
{
	public GameObject player;
	public GameObject ui_manager;
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
		if(player.activeSelf && !ui_manager.GetComponent<UIManager>().isUIOpen()){
			player.GetComponent<PlayerMovement>().enterShop();
			gameObject.SetActive(true);
		}
	}

	public void closeUI(){
		player.GetComponent<PlayerMovement>().exitShop();
		gameObject.SetActive(false);
	}
}
