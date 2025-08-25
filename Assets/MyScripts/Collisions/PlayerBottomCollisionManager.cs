using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class PlayerBottomCollisionManager : MonoBehaviour
{
    // Start is called before the first frame update
    void Start()
    {
        
    }

    // Update is called once per frame
    void Update()
    {
        
    }
	
	void OnTriggerEnter2D(Collider2D collision){
		if (collision.CompareTag("Ground")){
			transform.parent.GetComponent<PlayerMovement>().isOnGround = true;
		}
	}

	void OnTriggerExit2D(Collider2D collision){
		if (collision.CompareTag("Ground")){
			transform.parent.GetComponent<PlayerMovement>().isOnGround = false;
		}
	}
	
	void OnTriggerStay2D(Collider2D collision){
		if (collision.CompareTag("Ground")){
			transform.parent.GetComponent<PlayerMovement>().isOnGround = true;
		}
	}
}
