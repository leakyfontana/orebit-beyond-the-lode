using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using TMPro;

public class P1BossMethods : MonoBehaviour
{
	public GameObject player;
	public GameObject transmission_manager;
	public GameObject burst_particles;
	public GameObject small_burst_particles;
	public GameObject sustained_particles;
	public GameObject boss_health_object;
	public GameObject boss_health_bar;
	public GameObject boss_health_text;
	public GameObject p1_boss_head;
	public GameObject p2_boss_head;
	public GameObject stick_attack_hitbox_gameobject;
	public GameObject laser_attack_gameobject;
	public GameObject phase_two;
	[HideInInspector]
	public bool is_facing_left;
	public float max_hp;
	public float hp;
	//Invincibility
	[Header("Invincibility")]
	public bool is_invincible;
	public float invincibility_time;
	public float invincibility_time_left;
	public int frames_of_invisibility;
	public int frames_of_invisibility_left;
    // Start is called before the first frame update
    void Start()
    {
		
    }
	
	void OnEnable(){
		hp = max_hp;
		boss_health_object.SetActive(true);
		updateBossHealthUI();
	}

    // Update is called once per frame
    void Update()
    {
        if(is_invincible){
			invincibility_time_left -= Time.deltaTime;
			frames_of_invisibility_left -= 1;
			if(frames_of_invisibility_left <= 0){
				frames_of_invisibility_left = frames_of_invisibility;
				if(GetComponent<SpriteRenderer>().color.a == 0f){
					GetComponent<SpriteRenderer>().color = new Color(1f, 1f, 1f, 1f);
				}
				else {
					GetComponent<SpriteRenderer>().color = new Color(1f, 1f, 1f, 0f);
				}
			}
			if(invincibility_time_left <= 0){
				is_invincible = false;
				frames_of_invisibility_left = 0;
				GetComponent<SpriteRenderer>().color = new Color(1f, 1f, 1f, 1f);
			}
		}
    }
	
	public void finishOneWalkCycle(){
		turnTowardsPlayer();
		float random = Random.Range(0f,1f);
		if (random < 0.33f){
			GetComponent<Animator>().SetTrigger("StickAttack");
		}
		else if (random < 0.66f){
			GetComponent<Animator>().SetTrigger("LaserAttack");
		}
		Debug.Log(random);
	}
	
	public void turnTowardsPlayer(){
		if(player.transform.position.x < transform.position.x && !is_facing_left){
			flipBoss();
		}
		else if(player.transform.position.x > transform.position.x && is_facing_left){
			flipBoss();
		}
	}
	
	public void flipBoss(){
		Vector3 currentScale = gameObject.transform.localScale;
		currentScale.x *= -1;
		gameObject.transform.localScale = currentScale;
		is_facing_left = !is_facing_left;
	}
	
	public void deactivateCollisions(){
		foreach(Collider2D col in GetComponents<Collider2D>()){
			col.enabled = false;
		}
	}

	public void reactivateCollisions(){
		foreach(Collider2D col in GetComponents<Collider2D>()){
			col.enabled = true;
		}
	}
	
	public void activateLaserAttack(){
		laser_attack_gameobject.SetActive(true);
		laser_attack_gameobject.GetComponent<P1LaserAttackBehavior>().startAttack();
	}

	public void deactivateLaserAttack(){
		laser_attack_gameobject.SetActive(false);
	}
	
	private void updateBossHealthUI(){
		boss_health_bar.GetComponent<Slider>().value = hp / max_hp;
		boss_health_text.GetComponent<TextMeshProUGUI>().text = (int) hp + "/" + (int) max_hp;
	}
	
	public void loseHP(int amount){
		if(!is_invincible){
			//PLAY SOUND OF BOSS TAKING DAMAGE?
			hp -= amount;
			if (hp <= 0){
				hp = 0;
				GetComponent<Animator>().SetTrigger("DeathTrigger");
				//death
			}
			else {
				is_invincible = true;
				invincibility_time_left = invincibility_time;
			}
			if(Random.Range(0f, 1f) < 0.5f)
				playSound("P1Damage1");
			else
				playSound("P1Damage2");
			updateBossHealthUI();			
		}
	}
	
	public void playTransmission(){
		transmission_manager.GetComponent<TransmissionManager>().displayTransmission(12);
	}
	
	public void finishDeath(){
		phase_two.SetActive(true);
		phase_two.transform.position = new Vector2(transform.position.x, phase_two.transform.position.y); //Moves the phase two X position to the X position of pahse one death
		p1_boss_head.SetActive(false);
		p2_boss_head.SetActive(true);
		Destroy(gameObject);
	}
	
	public void playSound(string sound_name){
		FindObjectOfType<AudioManager>().PlaySoundOneShot(sound_name);
	}
	
	public void startSustainedParticles(){
		sustained_particles.GetComponent<ParticleSystem>().Play();
	}

	public void stopSustainedParticles(){
		sustained_particles.GetComponent<ParticleSystem>().Stop();
	}
	
	public void startBurstParticles(){
		burst_particles.GetComponent<ParticleSystem>().Play();
	}

	public void startSmallBurstParticles(){
		small_burst_particles.GetComponent<ParticleSystem>().Play();
	}
}
